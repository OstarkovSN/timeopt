import sqlite3
import logging
import uuid as _uuid
from datetime import datetime, timezone, timedelta
from enum import Enum
from timeopt.core import get_all_config

logger = logging.getLogger(__name__)


class EisenhowerQ(str, Enum):
    Q1 = "Q1"  # urgent + important
    Q2 = "Q2"  # important, not urgent
    Q3 = "Q3"  # urgent, not important
    Q4 = "Q4"  # neither


_Q_ORDER = {EisenhowerQ.Q1: 0, EisenhowerQ.Q2: 1, EisenhowerQ.Q3: 2, EisenhowerQ.Q4: 3}
_PRIORITY_IMPORTANT = {"high", "medium"}


def eisenhower_quadrant(priority: str, urgent: bool) -> EisenhowerQ:
    """Map priority + urgent to Eisenhower quadrant."""
    important = priority in _PRIORITY_IMPORTANT
    if urgent and important:
        return EisenhowerQ.Q1
    if important and not urgent:
        return EisenhowerQ.Q2
    if urgent and not important:
        return EisenhowerQ.Q3
    return EisenhowerQ.Q4


def classify_tasks(
    conn: sqlite3.Connection, task_ids: list[str] | None = None
) -> list[dict]:
    """
    Run Eisenhower classification on active tasks.
    Upgrades urgency for overdue/due-today tasks.
    Returns tasks sorted by quadrant order.
    If task_ids provided, only classifies those tasks.
    """
    today_end = datetime.now(timezone.utc).date().isoformat() + "T23:59:59"

    # Auto-upgrade urgency for overdue tasks
    if task_ids:
        placeholders = ",".join("?" * len(task_ids))
        conn.execute(
            f"UPDATE tasks SET urgent=1 "
            f"WHERE id IN ({placeholders}) "
            f"AND status IN ('pending','delegated') "
            f"AND due_at IS NOT NULL AND due_at <= ? AND urgent=0",
            (*task_ids, today_end),
        )
    else:
        conn.execute(
            "UPDATE tasks SET urgent=1 "
            "WHERE status IN ('pending','delegated') "
            "AND due_at IS NOT NULL AND due_at <= ? AND urgent=0",
            (today_end,),
        )
    conn.commit()

    where = ""
    params: list = []
    if task_ids:
        placeholders = ",".join("?" * len(task_ids))
        where = f"WHERE id IN ({placeholders}) AND status IN ('pending','delegated')"
        params = list(task_ids)
    else:
        where = "WHERE status IN ('pending','delegated')"

    rows = conn.execute(
        f"SELECT id, display_id, title, priority, urgent, category, effort, "
        f"due_at, status FROM tasks {where}",
        params,
    ).fetchall()

    results = []
    for row in rows:
        q = eisenhower_quadrant(row["priority"], bool(row["urgent"]))
        results.append({
            "task_id": row["id"],
            "display_id": row["display_id"],
            "title": row["title"],
            "priority": row["priority"],
            "urgent": bool(row["urgent"]),
            "effort": row["effort"],
            "due_at": row["due_at"],
            "quadrant": q.value,
        })

    results.sort(key=lambda x: _Q_ORDER[EisenhowerQ(x["quadrant"])])
    logger.info("classify_tasks: classified %d tasks", len(results))
    return results


def _parse_time(date_str: str, time_str: str) -> datetime:
    """Combine a date string (YYYY-MM-DD) and time string (HH:MM) into UTC datetime."""
    return datetime.fromisoformat(f"{date_str}T{time_str}:00+00:00")


def _effort_minutes(effort: str | None, config: dict) -> int:
    def _safe_int(val, default: int, label: str) -> int:
        try:
            return int(val)
        except (ValueError, TypeError):
            logger.warning("_effort_minutes: %s is not a valid integer, using default %d", label, default)
            return default

    mapping = {
        "small": _safe_int(config["effort_small_min"], 30, "effort_small_min"),
        "medium": _safe_int(config["effort_medium_min"], 60, "effort_medium_min"),
        "large": _safe_int(config["effort_large_min"], 120, "effort_large_min"),
    }
    return mapping.get(effort or "medium", _safe_int(config["effort_medium_min"], 60, "effort_medium_min"))


def _compute_free_slots(
    date: str,
    events: list[dict],
    day_start: datetime,
    day_end: datetime,
) -> list[tuple[datetime, datetime]]:
    """Return list of (start, end) free time slots given calendar events."""
    busy = []
    for ev in events:
        s = datetime.fromisoformat(ev["start"].replace("Z", "+00:00"))
        e = datetime.fromisoformat(ev["end"].replace("Z", "+00:00"))
        # Ensure offset-aware
        if s.tzinfo is None:
            s = s.replace(tzinfo=timezone.utc)
        if e.tzinfo is None:
            e = e.replace(tzinfo=timezone.utc)
        busy.append((s, e))
    busy.sort(key=lambda x: x[0])

    slots = []
    cursor = day_start
    for s, e in busy:
        if cursor < s:
            slots.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < day_end:
        slots.append((cursor, day_end))
    return slots


def get_plan_proposal(
    conn: sqlite3.Connection,
    events: list[dict],
    date: str | None = None,
) -> dict:
    """
    Compute a time-blocked schedule for the given date.

    Args:
        conn: SQLite connection
        events: List of {start, end, title} calendar events (ISO8601 strings)
        date: YYYY-MM-DD string, defaults to today UTC

    Returns:
        {
            "blocks": [{task_id, display_id, title, start, duration_min, quadrant}],
            "deferred": [{task_id, display_id, title, quadrant}],
        }
    """
    if date is None:
        date = datetime.now(timezone.utc).date().isoformat()

    config = get_all_config(conn)
    day_start = _parse_time(date, config["day_start"])
    day_end = _parse_time(date, config["day_end"])
    try:
        break_min = int(config["break_duration_min"])
    except (ValueError, TypeError):
        logger.warning("get_plan_proposal: break_duration_min is not a valid integer, using default 10")
        break_min = 10

    free_slots = _compute_free_slots(date, events, day_start, day_end)
    tasks = classify_tasks(conn)  # sorted Q1→Q4, urgency upgraded

    blocks = []
    deferred = []
    slot_idx = 0
    cursor: datetime | None = free_slots[0][0] if free_slots else None

    for task in tasks:
        duration = _effort_minutes(task.get("effort"), config)

        # Find a slot that fits
        scheduled = False
        while slot_idx < len(free_slots):
            slot_start, slot_end = free_slots[slot_idx]
            if cursor is None or cursor < slot_start:
                cursor = slot_start

            available = (slot_end - cursor).seconds // 60
            # Need space for duration + break (unless last item)
            needed = duration + break_min
            if available >= needed:
                block_start = cursor.isoformat()
                blocks.append({
                    "task_id": task["task_id"],
                    "display_id": task["display_id"],
                    "title": task["title"],
                    "start": block_start,
                    "duration_min": duration,
                    "quadrant": task["quadrant"],
                })
                cursor = cursor + timedelta(minutes=duration + break_min)
                scheduled = True
                break
            else:
                slot_idx += 1
                cursor = None

        if not scheduled:
            deferred.append({
                "task_id": task["task_id"],
                "display_id": task["display_id"],
                "title": task["title"],
                "quadrant": task["quadrant"],
            })

    logger.info(
        "get_plan_proposal: %d blocks, %d deferred for %s",
        len(blocks), len(deferred), date,
    )
    return {"blocks": blocks, "deferred": deferred}


def save_calendar_blocks(
    conn: sqlite3.Connection,
    blocks: list[dict],
    plan_date: str,
    caldav_uids: list[str],
) -> None:
    """
    Persist calendar blocks after successful CalDAV push.
    caldav_uids must be the same length and order as blocks.
    """
    assert len(blocks) == len(caldav_uids), "blocks and caldav_uids must match"
    for block, uid in zip(blocks, caldav_uids):
        conn.execute(
            "INSERT INTO calendar_blocks(id, task_id, caldav_uid, scheduled_at, duration_min, plan_date) "
            "VALUES (?,?,?,?,?,?)",
            (
                str(_uuid.uuid4()),
                block["task_id"],
                uid,
                block["start"],
                block["duration_min"],
                plan_date,
            ),
        )
    conn.commit()
    logger.info("saved %d calendar blocks for %s", len(blocks), plan_date)


def delete_calendar_blocks_for_date(
    conn: sqlite3.Connection, plan_date: str
) -> list[str]:
    """
    Delete all calendar_blocks rows for a date.
    Returns list of caldav_uids that must be deleted from CalDAV by the caller.
    """
    rows = conn.execute(
        "SELECT caldav_uid FROM calendar_blocks WHERE plan_date=?", (plan_date,)
    ).fetchall()
    uids = [row[0] for row in rows]
    conn.execute("DELETE FROM calendar_blocks WHERE plan_date=?", (plan_date,))
    conn.commit()
    logger.info("deleted %d calendar blocks for %s", len(uids), plan_date)
    return uids


def get_calendar_blocks(
    conn: sqlite3.Connection, plan_date: str
) -> list[dict]:
    """Return all calendar blocks for a date."""
    rows = conn.execute(
        "SELECT id, task_id, caldav_uid, scheduled_at, duration_min, plan_date "
        "FROM calendar_blocks WHERE plan_date=?",
        (plan_date,),
    ).fetchall()
    return [dict(row) for row in rows]


def _get_uids_for_date(conn: sqlite3.Connection, date: str) -> list[str]:
    rows = conn.execute(
        "SELECT caldav_uid FROM calendar_blocks WHERE plan_date=?", (date,)
    ).fetchall()
    return [row[0] for row in rows]


def push_calendar_blocks(
    conn: sqlite3.Connection,
    proposal: dict,
    date: str,
    caldav_client,
) -> None:
    """
    Transactional push: all CalDAV writes collected first,
    SQLite committed only on full success.
    If CalDAV fails, raises and leaves DB unchanged.
    """
    blocks = proposal["blocks"]
    if not blocks:
        logger.info("push_calendar_blocks: no blocks to push for %s", date)
        return

    # Step 1: collect old UIDs that need deletion (from DB, before changes)
    old_uids = _get_uids_for_date(conn, date)

    # Step 2: attempt ALL CalDAV creates first (may raise — leaves DB untouched)
    new_uids = []
    for block in blocks:
        end_dt = (
            datetime.fromisoformat(block["start"]) +
            timedelta(minutes=block["duration_min"])
        ).isoformat()
        uid = caldav_client.create_event(
            title=block["title"],
            start=block["start"],
            end=end_dt,
        )
        new_uids.append(uid)

    # Step 3: all creates succeeded — delete old CalDAV events
    for uid in old_uids:
        caldav_client.delete_event(uid)

    # Step 4: commit SQLite atomically
    conn.execute("DELETE FROM calendar_blocks WHERE plan_date=?", (date,))
    for block, uid in zip(blocks, new_uids):
        conn.execute(
            "INSERT INTO calendar_blocks(id, task_id, caldav_uid, scheduled_at, duration_min, plan_date) "
            "VALUES (?,?,?,?,?,?)",
            (str(_uuid.uuid4()), block["task_id"], uid, block["start"], block["duration_min"], date),
        )
    conn.commit()
    logger.info("push_calendar_blocks: pushed %d blocks for %s", len(blocks), date)
