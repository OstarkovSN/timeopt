import json
import sqlite3
import logging
import re
import uuid
from typing import Any
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from rapidfuzz import process as fuzz_process

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

# Optional keys — no default, return None if unset
_CONFIG_OPTIONAL: frozenset[str] = frozenset({
    "caldav_url", "caldav_username", "caldav_password",
    "caldav_read_calendars", "caldav_tasks_calendar",
    "llm_base_url", "llm_api_key", "llm_model",
})


def get_config(conn: sqlite3.Connection, key: str) -> str | None:
    """Return config value. Raises KeyError for unknown keys.
    Optional keys (caldav_*, llm_*) return None if unset."""
    if key not in _CONFIG_DEFAULTS and key not in _CONFIG_OPTIONAL:
        raise KeyError("Unknown config key: %s" % key)
    row = conn.execute(
        "SELECT value FROM config WHERE key = ?", (key,)
    ).fetchone()
    if row:
        return row[0]
    return _CONFIG_DEFAULTS.get(key)  # None for optional keys


def set_config(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Persist a config value. Raises KeyError for unknown keys."""
    if key not in _CONFIG_DEFAULTS and key not in _CONFIG_OPTIONAL:
        raise KeyError("Unknown config key: %s" % key)
    conn.execute(
        "INSERT INTO config(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    logger.info("config set: %s = %s", key, value)


def get_all_config(conn: sqlite3.Connection) -> dict[str, str | None]:
    """Return all config values, merging DB overrides with defaults.
    Optional keys (caldav_*, llm_*) are included with None if unset."""
    cfg: dict[str, str | None] = dict(_CONFIG_DEFAULTS)
    for key in _CONFIG_OPTIONAL:
        cfg[key] = None
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


_DISPLAY_FIELDS = (
    "display_id", "title", "priority", "urgent", "category",
    "effort", "due_at", "status", "due_event_label", "due_unresolved",
    "done_at", "notes",
)


def _auto_classify(conn: sqlite3.Connection) -> None:
    """Upgrade urgency for tasks with due_at today or overdue. Called automatically."""
    today = datetime.now(timezone.utc).date().isoformat()
    conn.execute(
        "UPDATE tasks SET urgent=1 "
        "WHERE status IN ('pending','delegated') "
        "AND due_at IS NOT NULL AND due_at <= ? AND urgent=0",
        (today + "T23:59:59",),
    )
    conn.commit()


def list_tasks(
    conn: sqlite3.Connection,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    include_old_done: bool = False,
) -> list[dict]:
    """
    Return tasks as dicts with display fields only.
    Defaults to pending + delegated. Auto-upgrades urgency before returning.
    """
    _auto_classify(conn)

    hide_days = int(get_config(conn, "hide_done_after_days"))
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=hide_days)
    ).isoformat()

    clauses = []
    params: list[Any] = []

    if status:
        clauses.append("status = ?")
        params.append(status)
    else:
        if include_old_done:
            pass  # no filter
        else:
            clauses.append(
                "(status IN ('pending','delegated') OR "
                "(status='done' AND done_at >= ?))"
            )
            params.append(cutoff)

    if priority:
        clauses.append("priority = ?")
        params.append(priority)
    if category:
        clauses.append("category = ?")
        params.append(category)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    fields = ", ".join(_DISPLAY_FIELDS)
    rows = conn.execute(
        f"SELECT {fields} FROM tasks {where} ORDER BY rowid", params
    ).fetchall()

    result = []
    for row in rows:
        d = dict(zip(_DISPLAY_FIELDS, row))
        if d.get("notes"):
            d["notes"] = d["notes"][-60:]
        result.append(d)
    return result


def get_task(conn: sqlite3.Connection, task_id: str) -> dict:
    """Return full task dict by UUID. Raises ValueError if not found."""
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise ValueError("Task not found: %s" % task_id)
    return dict(row)


def fuzzy_match_tasks(
    conn: sqlite3.Connection, query: str, limit: int = 5
) -> list[dict]:
    """
    Fuzzy-match query against active task titles.
    Returns list of {task_id, display_id, title, score} sorted by score desc.
    Only searches pending and delegated tasks.
    """
    rows = conn.execute(
        "SELECT id, display_id, title FROM tasks "
        "WHERE status IN ('pending', 'delegated')"
    ).fetchall()

    if not rows:
        return []

    titles = [row["title"] for row in rows]
    results = fuzz_process.extract(query, titles, limit=limit)

    matches = []
    for title, score, idx in results:
        row = rows[idx]
        matches.append({
            "task_id": row["id"],
            "display_id": row["display_id"],
            "title": row["title"],
            "score": score,
        })
    return sorted(matches, key=lambda x: x["score"], reverse=True)


# Patterns suggesting an explicit time reference (not a calendar event)
_TIME_PATTERNS = [
    r"\b(before|by|at|until)\s+\d{1,2}(:\d{2})?\s*(am|pm)?\b",
    r"\b(noon|midnight|morning|evening|tonight)\b",
    r"\bby\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\b(today|tomorrow|this week|next week)\b",
    r"\bfor\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
]
_TIME_RE = re.compile("|".join(_TIME_PATTERNS), re.IGNORECASE)

# Patterns suggesting a calendar event reference
_EVENT_PATTERNS = [
    r"\b(before|after|during|ahead of|prior to)\s+(?:the\s+)?(?:meeting|call|standup|review|sync|session|presentation|interview|lunch|dinner)\b",
    r"\bbefore\s+(?:my\s+)?(?:meeting|call)\s+with\b",
]
_EVENT_RE = re.compile("|".join(_EVENT_PATTERNS), re.IGNORECASE)

_TEMPLATE_SCHEMA = {
    "priority": "high|medium|low",
    "urgent": "bool",
    "category": "work|personal|errands|other",
    "effort": "small|medium|large",
    "due_at": "ISO8601 UTC or omit",
    "due_event_label": "string or omit",
    "due_event_offset_min": "int (negative = before event) or omit",
}


def _extract_event_label(fragment: str) -> str | None:
    """Try to extract the event name from a textual calendar reference."""
    patterns = [
        r"\bbefore\s+(?:my\s+)?((?:meeting|call)\s+with\s+.+?)(?:\s*$)",
        r"\b(?:before|after|during|ahead of|prior to)\s+(?:the\s+)?(.+?)(?:\s*$)",
    ]
    for pat in patterns:
        m = re.search(pat, fragment, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def resolve_calendar_reference(
    label: str,
    events: list,
) -> dict | None:
    """
    Fuzzy-match a textual event label against a list of CalendarEvent objects.
    Returns the best match as {uid, title, start, end, score} or None.
    """
    if not events:
        return None
    titles = [ev.title for ev in events]
    results = fuzz_process.extractOne(label, titles)
    if results is None:
        return None
    title, score, idx = results
    if score < 50:
        return None
    ev = events[idx]
    return {"uid": ev.uid, "title": ev.title, "start": ev.start, "end": ev.end, "score": score}


def get_dump_templates(
    fragments: list[str],
    events: list,
) -> dict:
    """
    Build sparse JSON templates for brain-dump fragments.
    Schema appears once at top level. Only non-null fields included per template.
    events: list of CalendarEvent objects for reference resolution.
    """
    templates = []
    for fragment in fragments:
        tmpl: dict = {
            "raw": fragment,
            "title": fragment.strip(),
            "priority": "?",
            "urgent": "?",
            "category": "?",
            "effort": "?",
        }

        # Detect explicit time reference
        if _TIME_RE.search(fragment):
            tmpl["due_at"] = "?"

        # Detect calendar event reference
        if _EVENT_RE.search(fragment):
            label = _extract_event_label(fragment)
            if label:
                tmpl["due_event_label"] = label
                tmpl["due_event_offset_min"] = "?"
                # Try to resolve now
                match = resolve_calendar_reference(label, events)
                if match:
                    tmpl["_resolved_event_uid"] = match["uid"]

        templates.append(tmpl)

    return {"schema": _TEMPLATE_SCHEMA, "templates": templates}


def dump_task(conn: sqlite3.Connection, task: TaskInput) -> str:
    """
    Save a single task from a filled template.
    Auto-runs Eisenhower classification after insert.
    Returns display_id.
    """
    display_id = create_task(conn, task)
    # Auto-classify: upgrade urgency if overdue
    _auto_classify(conn)
    logger.info("dump_task: saved %s", display_id)
    return display_id


def dump_tasks(conn: sqlite3.Connection, tasks: list[TaskInput]) -> list[str]:
    """
    Save a batch of tasks from filled templates.
    Auto-runs Eisenhower classification once after all inserts.
    Returns list of display_ids.
    """
    display_ids = [create_task(conn, task) for task in tasks]
    _auto_classify(conn)
    logger.info("dump_tasks: saved %d tasks", len(display_ids))
    return display_ids


def sync_bound_tasks(conn: sqlite3.Connection, events: list) -> list[dict]:
    """
    Algorithmic sync: update due_at for bound tasks based on current calendar events.
    Returns list of changes: {display_id, old_due_at, new_due_at, status}
    status: "updated" | "event_missing"
    Only touches tasks with due_event_uid set.
    """
    rows = conn.execute(
        "SELECT id, display_id, due_event_uid, due_event_offset_min, due_at "
        "FROM tasks WHERE due_event_uid IS NOT NULL AND status IN ('pending','delegated')"
    ).fetchall()

    if not rows:
        return []

    events_by_uid = {ev.uid: ev for ev in events}
    changes = []

    for row in rows:
        uid = row["due_event_uid"]
        offset = row["due_event_offset_min"] or 0

        if uid not in events_by_uid:
            changes.append({
                "display_id": row["display_id"],
                "old_due_at": row["due_at"],
                "new_due_at": row["due_at"],  # preserved
                "status": "event_missing",
            })
            continue

        ev = events_by_uid[uid]
        event_start = datetime.fromisoformat(ev.start.replace("Z", "+00:00"))
        new_due_at = (event_start + timedelta(minutes=offset)).isoformat()

        if new_due_at != row["due_at"]:
            conn.execute(
                "UPDATE tasks SET due_at=? WHERE id=?", (new_due_at, row["id"])
            )
            changes.append({
                "display_id": row["display_id"],
                "old_due_at": row["due_at"],
                "new_due_at": new_due_at,
                "status": "updated",
            })

    conn.commit()
    logger.info("sync_bound_tasks: %d changes", len(changes))
    return changes


def get_unresolved_tasks(conn: sqlite3.Connection) -> list[dict]:
    """Return tasks with due_unresolved=True."""
    rows = conn.execute(
        "SELECT id, display_id, due_event_label FROM tasks "
        "WHERE due_unresolved=1 AND status IN ('pending','delegated')"
    ).fetchall()
    return [dict(row) for row in rows]


def try_resolve_unresolved(conn: sqlite3.Connection, events: list) -> list[dict]:
    """
    Attempt to bind unresolved tasks to calendar events.
    Returns list of {display_id, status: "resolved" | "still_unresolved"}.
    """
    unresolved = get_unresolved_tasks(conn)
    results = []
    for task in unresolved:
        label = task["due_event_label"]
        if not label:
            continue
        match = resolve_calendar_reference(label, events)
        if match:
            event_start = datetime.fromisoformat(
                match["start"].replace("Z", "+00:00")
            )
            row = conn.execute(
                "SELECT due_event_offset_min FROM tasks WHERE id=?", (task["id"],)
            ).fetchone()
            offset = row[0] if row and row[0] is not None else 0
            new_due_at = (event_start + timedelta(minutes=offset)).isoformat()
            conn.execute(
                "UPDATE tasks SET due_event_uid=?, due_at=?, due_unresolved=0 WHERE id=?",
                (match["uid"], new_due_at, task["id"]),
            )
            conn.commit()
            results.append({"display_id": task["display_id"], "status": "resolved"})
            logger.info("resolved task %s to event uid=%s", task["display_id"], match["uid"])
        else:
            results.append({"display_id": task["display_id"], "status": "still_unresolved"})
    return results


def _parse_json_array(text: str) -> list:
    """Extract a JSON array from LLM response text (strips markdown/preamble)."""
    match = re.search(r'\[[\s\S]*\]', text)
    if not match:
        raise ValueError(f"LLM response contained no JSON array: {text[:200]}")
    return json.loads(match.group())


def cli_dump(conn: sqlite3.Connection, llm_client, raw_text: str) -> dict:
    """
    CLI brain dump: split raw text, get templates, fill via LLM, save.
    Returns {count, display_ids}.
    """
    fragments = [f.strip() for f in re.split(r'[,;]|(?<!\w)and(?!\w)', raw_text)
                 if f.strip()]
    templates_result = get_dump_templates(fragments, events=[])

    system = (
        "You are a task parser. Fill every '?' in each template using context from the task "
        "description. Return ONLY a valid JSON array — no markdown, no explanation. "
        "Valid values are in the schema. Omit optional fields (due_at, due_event_label, "
        "due_event_offset_min) unless the task clearly implies them."
    )
    user = (
        f"Schema: {json.dumps(templates_result['schema'])}\n\n"
        f"Templates:\n{json.dumps(templates_result['templates'], indent=2)}"
    )

    raw_response = llm_client.complete(system=system, user=user)
    filled = _parse_json_array(raw_response)

    task_inputs = [
        TaskInput(
            title=t.get("title", ""),
            raw=t.get("raw") or t.get("title", ""),
            priority=t.get("priority", "medium"),
            urgent=bool(t.get("urgent", False)),
            category=t.get("category", "other"),
            effort=t.get("effort") or None,
            due_at=t.get("due_at"),
            due_event_label=t.get("due_event_label"),
            due_event_offset_min=t.get("due_event_offset_min"),
        )
        for t in filled
    ]
    display_ids = dump_tasks(conn, task_inputs)
    logger.info("cli_dump: saved %d tasks", len(display_ids))
    return {"count": len(display_ids), "display_ids": display_ids}
