import sqlite3
import logging
import re
import uuid
from typing import Any
from datetime import datetime, timezone
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_CONFIG_DEFAULTS: dict[str, str] = {
    "day_start": "09:00",
    "day_end": "18:00",
    "break_duration_min": "15",
    "default_effort": "medium",
    "effort_small_min": "30",
    "effort_medium_min": "60",
    "effort_large_min": "120",
    "hide_done_after_days": "7",
    "fuzzy_match_min_score": "80",
    "fuzzy_match_ask_gap": "10",
    "delegation_max_tool_calls": "10",
}


def get_config(conn: sqlite3.Connection, key: str) -> str:
    """Return config value. Raises KeyError for unknown keys."""
    if key not in _CONFIG_DEFAULTS:
        raise KeyError("Unknown config key: %s" % key)
    row = conn.execute(
        "SELECT value FROM config WHERE key = ?", (key,)
    ).fetchone()
    if row:
        return row[0]
    return _CONFIG_DEFAULTS[key]


def set_config(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Persist a config value. Raises KeyError for unknown keys."""
    if key not in _CONFIG_DEFAULTS:
        raise KeyError("Unknown config key: %s" % key)
    conn.execute(
        "INSERT INTO config(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    logger.info("config set: %s = %s", key, value)


def get_all_config(conn: sqlite3.Connection) -> dict[str, str]:
    """Return all config values, merging DB overrides with defaults."""
    cfg = dict(_CONFIG_DEFAULTS)
    for row in conn.execute("SELECT key, value FROM config").fetchall():
        cfg[row[0]] = row[1]
    return cfg


@dataclass
class TaskInput:
    title: str
    raw: str
    priority: str          # high | medium | low
    urgent: bool
    category: str          # work | personal | errands | other
    effort: str | None = None
    due_at: str | None = None
    due_event_uid: str | None = None
    due_event_label: str | None = None
    due_event_offset_min: int | None = None
    due_unresolved: bool = False


def _slugify(text: str) -> str:
    """Convert title to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:60]  # cap length


def create_task(conn: sqlite3.Connection, task: TaskInput) -> str:
    """
    Insert a new task. Returns the assigned display_id.
    Runs Eisenhower classification before insert.
    """
    from timeopt.db import next_short_id

    short_id = next_short_id(conn)
    slug = _slugify(task.title)
    display_id = f"#{short_id}-{slug}"
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    effort = task.effort or get_config(conn, "default_effort")

    conn.execute(
        """INSERT INTO tasks(
            id, short_id, display_id, title, raw, priority, urgent, category,
            effort, due_at, due_event_uid, due_event_label, due_event_offset_min,
            due_unresolved, created_at, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            task_id, short_id, display_id, task.title, task.raw,
            task.priority, int(task.urgent), task.category,
            effort, task.due_at, task.due_event_uid, task.due_event_label,
            task.due_event_offset_min, int(task.due_unresolved), now, "pending",
        ),
    )
    conn.commit()
    logger.info("task created: %s %s", display_id, task.title)
    return display_id


def _append_note(conn: sqlite3.Connection, task_id: str, text: str) -> None:
    """Append a timestamped entry to task notes."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"[{now}] {text}"
    existing = conn.execute(
        "SELECT notes FROM tasks WHERE id=?", (task_id,)
    ).fetchone()[0]
    new_notes = f"{existing}\n{entry}" if existing else entry
    conn.execute("UPDATE tasks SET notes=? WHERE id=?", (new_notes, task_id))
    conn.commit()


def mark_done(conn: sqlite3.Connection, task_ids: list[str]) -> None:
    """
    Mark tasks as done. task_ids may be UUIDs or display_ids.
    Only acts on pending/delegated tasks — raises ValueError otherwise.
    """
    for task_id in task_ids:
        row = conn.execute(
            "SELECT id, status FROM tasks WHERE id=? OR display_id=?",
            (task_id, task_id),
        ).fetchone()
        if not row:
            raise ValueError("Task not found: %s" % task_id)
        if row["status"] not in ("pending", "delegated"):
            raise ValueError("Task %s is not active (status=%s)" % (task_id, row["status"]))
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE tasks SET status='done', done_at=? WHERE id=?",
            (now, row["id"]),
        )
        conn.commit()
        logger.info("task done: %s", row["id"])


def mark_delegated(
    conn: sqlite3.Connection, task_id: str, notes: str | None = None
) -> None:
    """Set task status to delegated. task_id is UUID or display_id."""
    row = conn.execute(
        "SELECT id FROM tasks WHERE (id=? OR display_id=?) AND status='pending'",
        (task_id, task_id),
    ).fetchone()
    if not row:
        raise ValueError("Pending task not found: %s" % task_id)
    conn.execute("UPDATE tasks SET status='delegated' WHERE id=?", (row["id"],))
    conn.commit()
    if notes:
        _append_note(conn, row["id"], notes)
    logger.info("task delegated: %s", row["id"])


def update_task_notes(
    conn: sqlite3.Connection, task_id: str, notes: str
) -> None:
    """Append progress note to a delegated task. Raises if not delegated."""
    row = conn.execute(
        "SELECT id, status FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    if not row or row["status"] != "delegated":
        raise ValueError("Task %s is not delegated" % task_id)
    _append_note(conn, task_id, notes)


def return_to_pending(
    conn: sqlite3.Connection, task_id: str, notes: str
) -> None:
    """Return a delegated task to pending with a failure note."""
    row = conn.execute(
        "SELECT id FROM tasks WHERE id=? AND status='delegated'", (task_id,)
    ).fetchone()
    if not row:
        raise ValueError("Delegated task not found: %s" % task_id)
    _append_note(conn, task_id, notes)
    conn.execute("UPDATE tasks SET status='pending' WHERE id=?", (task_id,))
    conn.commit()
    logger.info("task returned to pending: %s", task_id)
