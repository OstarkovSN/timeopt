import pytest
from datetime import datetime, timezone, timedelta
from timeopt.core import create_task, TaskInput, get_config
from timeopt.planner import eisenhower_quadrant, classify_tasks, EisenhowerQ


def _task(title, priority, urgent):
    return TaskInput(title=title, raw=title, priority=priority,
                     urgent=urgent, category="work", effort="medium")


def test_q1_urgent_important(conn):
    assert eisenhower_quadrant("high", True) == EisenhowerQ.Q1
    assert eisenhower_quadrant("medium", True) == EisenhowerQ.Q1


def test_q2_important_not_urgent(conn):
    assert eisenhower_quadrant("high", False) == EisenhowerQ.Q2
    assert eisenhower_quadrant("medium", False) == EisenhowerQ.Q2


def test_q3_urgent_not_important(conn):
    assert eisenhower_quadrant("low", True) == EisenhowerQ.Q3


def test_q4_neither(conn):
    assert eisenhower_quadrant("low", False) == EisenhowerQ.Q4


def test_classify_tasks_upgrades_urgency_for_overdue(conn):
    past_due = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    t = TaskInput(title="overdue task", raw="overdue", priority="medium",
                  urgent=False, category="work", effort="small", due_at=past_due)
    display_id = create_task(conn, t)
    classify_tasks(conn)
    row = conn.execute("SELECT urgent FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    assert row[0] == 1


def test_classify_tasks_sorts_by_quadrant(conn):
    create_task(conn, _task("q4 task", "low", False))
    create_task(conn, _task("q1 task", "high", True))
    create_task(conn, _task("q2 task", "high", False))
    create_task(conn, _task("q3 task", "low", True))
    results = classify_tasks(conn)
    quadrants = [r["quadrant"] for r in results]
    assert quadrants == ["Q1", "Q2", "Q3", "Q4"]
