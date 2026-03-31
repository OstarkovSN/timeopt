from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta
from timeopt.core import (
    create_task, TaskInput, sync_bound_tasks, get_unresolved_tasks
)
from timeopt.caldav_client import CalendarEvent


def _bound_task(conn, due_event_uid="uid-jeff", due_at="2026-03-28T13:30:00+00:00"):
    task = TaskInput(
        title="prep report", raw="prep before meeting with Jeff",
        priority="high", urgent=False, category="work", effort="large",
        due_at=due_at,
        due_event_uid=due_event_uid,
        due_event_label="meeting with Jeff",
        due_event_offset_min=-30,
    )
    return create_task(conn, task)


def test_sync_bound_tasks_updates_due_at(conn):
    display_id = _bound_task(conn)
    # Event has moved to Thursday
    updated_events = [
        CalendarEvent(
            uid="uid-jeff",
            title="Meeting with Jeff",
            start="2026-03-30T14:00:00+00:00",  # moved
            end="2026-03-30T15:00:00+00:00",
        )
    ]
    changes = sync_bound_tasks(conn, updated_events)
    assert len(changes) == 1
    assert changes[0]["display_id"] == display_id
    row = conn.execute(
        "SELECT due_at FROM tasks WHERE display_id=?", (display_id,)
    ).fetchone()
    # due_at should be 30 min before new event start
    assert "2026-03-30T13:30" in row[0]


def test_sync_bound_tasks_warns_if_event_deleted(conn):
    display_id = _bound_task(conn)
    # Event no longer in calendar
    changes = sync_bound_tasks(conn, events=[])
    # Task's due_at preserved, but change flagged as "event_missing"
    assert any(c["status"] == "event_missing" for c in changes)


def test_sync_bound_tasks_ignores_non_bound(conn):
    task = TaskInput(
        title="unbound task", raw="unbound",
        priority="low", urgent=False, category="other", effort="small",
        due_at="2026-03-28T10:00:00+00:00",
    )
    create_task(conn, task)
    changes = sync_bound_tasks(conn, events=[])
    assert len(changes) == 0  # non-bound task not touched


def test_get_unresolved_tasks_returns_due_unresolved(conn):
    task = TaskInput(
        title="board meeting prep", raw="prep before board meeting",
        priority="high", urgent=False, category="work", effort="large",
        due_event_label="board meeting",
        due_unresolved=True,
    )
    display_id = create_task(conn, task)
    unresolved = get_unresolved_tasks(conn)
    assert any(t["display_id"] == display_id for t in unresolved)


def test_sync_resolves_unresolved_when_event_appears(conn):
    task = TaskInput(
        title="board meeting prep", raw="prep before board meeting",
        priority="high", urgent=False, category="work", effort="large",
        due_event_label="board meeting",
        due_unresolved=True,
    )
    display_id = create_task(conn, task)
    events = [
        CalendarEvent(
            uid="uid-board",
            title="Board Meeting",
            start="2026-04-15T10:00:00+00:00",
            end="2026-04-15T11:00:00+00:00",
        )
    ]
    from timeopt.core import try_resolve_unresolved
    resolved = try_resolve_unresolved(conn, events)
    assert len(resolved) == 1
    row = conn.execute("SELECT due_unresolved, due_event_uid FROM tasks WHERE display_id=?",
                       (display_id,)).fetchone()
    assert row["due_unresolved"] == 0
    assert row["due_event_uid"] == "uid-board"
