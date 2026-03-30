import sqlite3
import logging
from datetime import datetime, timezone
from enum import Enum

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
