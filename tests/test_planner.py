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


from timeopt.planner import get_plan_proposal
from timeopt.core import set_config


def _seed_tasks(conn):
    """4 tasks across quadrants."""
    tasks = [
        _task("q1 deploy", "high", True),
        _task("q2 fix login", "high", False),
        _task("q2 prep slides", "medium", False),
        _task("q4 buy groceries", "low", False),
    ]
    for t in tasks:
        create_task(conn, t)


def test_plan_proposal_returns_blocks(conn):
    _seed_tasks(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    assert len(proposal["blocks"]) > 0
    assert "task_id" in proposal["blocks"][0]
    assert "start" in proposal["blocks"][0]
    assert "duration_min" in proposal["blocks"][0]


def test_plan_proposal_respects_calendar_events(conn):
    _seed_tasks(conn)
    events = [{"start": "2026-03-28T09:00:00", "end": "2026-03-28T12:00:00", "title": "big meeting"}]
    proposal = get_plan_proposal(conn, events=events, date="2026-03-28")
    for block in proposal["blocks"]:
        assert block["start"] >= "2026-03-28T12:00:00"


def test_plan_proposal_q1_scheduled_first(conn):
    _seed_tasks(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    first_block = proposal["blocks"][0]
    assert first_block["quadrant"] == "Q1"


def test_plan_proposal_inserts_breaks(conn):
    _seed_tasks(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    blocks = proposal["blocks"]
    if len(blocks) >= 2:
        end_first = _parse_end(blocks[0])
        start_second = blocks[1]["start"]
        gap_min = (_parse_dt(start_second) - end_first).seconds // 60
        assert gap_min >= 15  # break_duration_min default


def test_plan_proposal_defers_overflow(conn):
    set_config(conn, "day_end", "10:00")  # only 1 hour of work
    _seed_tasks(conn)  # 4 tasks, total effort > 1h
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    assert len(proposal["deferred"]) > 0


def _parse_dt(iso: str):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _parse_end(block: dict):
    start = _parse_dt(block["start"])
    return start + timedelta(minutes=block["duration_min"])


from timeopt.planner import save_calendar_blocks, delete_calendar_blocks_for_date, get_calendar_blocks


def test_save_calendar_blocks(conn):
    _seed_tasks(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    save_calendar_blocks(conn, proposal["blocks"], "2026-03-28",
                         caldav_uids=["uid-1", "uid-2", "uid-3", "uid-4"])
    blocks = get_calendar_blocks(conn, "2026-03-28")
    assert len(blocks) == len(proposal["blocks"])


def test_delete_calendar_blocks_for_date(conn):
    _seed_tasks(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    uids = [f"uid-{i}" for i in range(len(proposal["blocks"]))]
    save_calendar_blocks(conn, proposal["blocks"], "2026-03-28", caldav_uids=uids)
    delete_calendar_blocks_for_date(conn, "2026-03-28")
    assert get_calendar_blocks(conn, "2026-03-28") == []


def test_save_returns_stored_uids(conn):
    _seed_tasks(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    uids = [f"uid-{i}" for i in range(len(proposal["blocks"]))]
    save_calendar_blocks(conn, proposal["blocks"], "2026-03-28", caldav_uids=uids)
    blocks = get_calendar_blocks(conn, "2026-03-28")
    stored_uids = {b["caldav_uid"] for b in blocks}
    assert stored_uids == set(uids)


# ---------------------------------------------------------------------------
# Block 9: scheduling edge cases
# ---------------------------------------------------------------------------

def test_plan_proposal_zero_free_slots_all_deferred(conn):
    """Filling the entire day with one event leaves no free slots; all tasks deferred."""
    _seed_tasks(conn)  # 4 tasks
    # One all-day event covering day_start (09:00) to day_end (18:00)
    events = [{"start": "2026-03-28T09:00:00+00:00", "end": "2026-03-28T18:00:00+00:00",
               "title": "all day event"}]
    proposal = get_plan_proposal(conn, events=events, date="2026-03-28")
    assert proposal["blocks"] == []
    assert len(proposal["deferred"]) == 4


def test_plan_proposal_effort_none_uses_default(conn):
    """Task with effort=None falls back to default_effort config (medium=60 min)."""
    # Seed a task with effort=None
    t = TaskInput(title="no effort task", raw="no effort", priority="high",
                  urgent=False, category="work", effort=None)
    create_task(conn, t)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    assert len(proposal["blocks"]) == 1
    block = proposal["blocks"][0]
    assert block["duration_min"] == 60  # default_effort is "medium" = 60 min


def test_plan_proposal_events_before_day_start_dont_eat_slots(conn):
    """Event before day_start should not carve into available slots."""
    _seed_tasks(conn)
    # Event from 07:00 to 08:30, before day_start (09:00)
    events = [{"start": "2026-03-28T07:00:00+00:00", "end": "2026-03-28T08:30:00+00:00",
               "title": "pre-dawn event"}]
    proposal = get_plan_proposal(conn, events=events, date="2026-03-28")
    # Day_start is 09:00; first block should start at or after 09:00
    assert len(proposal["blocks"]) > 0
    first_start = datetime.fromisoformat(proposal["blocks"][0]["start"])
    day_start = datetime(2026, 3, 28, 9, 0, 0, tzinfo=timezone.utc)
    assert first_start >= day_start


def test_plan_proposal_overlapping_events_deduplicated(conn):
    """Two overlapping events should be deduplicated; blocks don't schedule within overlap.

    Tests that cursor = max(cursor, e) correctly deduplicates a contained event pair.
    Outer event: 10:00-11:30. Inner event: 10:15-11:00.
    With proper max() logic: after outer, cursor=11:30. Processing inner, max(11:30, 11:00)=11:30.
    With naive cursor=e: cursor would regress to 11:00, creating a phantom slot 11:00-11:30.
    """
    _seed_tasks(conn)
    # Two events where one is contained within the other
    # Outer: 10:00-11:30, Inner: 10:15-11:00 → combined busy: 10:00-11:30
    events = [
        {"start": "2026-03-28T10:00:00+00:00", "end": "2026-03-28T11:30:00+00:00", "title": "outer event"},
        {"start": "2026-03-28T10:15:00+00:00", "end": "2026-03-28T11:00:00+00:00", "title": "inner event"},
    ]
    proposal = get_plan_proposal(conn, events=events, date="2026-03-28")
    # Blocks should exist (they're deferred if they conflict, not removed)
    assert len(proposal["blocks"]) > 0
    # Verify no blocks are scheduled during 10:00-11:30
    for block in proposal["blocks"]:
        block_start = datetime.fromisoformat(block["start"])
        block_end = block_start + timedelta(minutes=block["duration_min"])
        busy_start = datetime.fromisoformat("2026-03-28T10:00:00+00:00")
        busy_end = datetime.fromisoformat("2026-03-28T11:30:00+00:00")
        # Block must not overlap [busy_start, busy_end]
        assert not (block_start < busy_end and block_end > busy_start)


def test_classify_tasks_with_specific_task_ids(conn):
    """classify_tasks with task_ids parameter only classifies those tasks."""
    from timeopt import core, planner

    # Create multiple tasks
    core.dump_task(conn, core.TaskInput(
        title="task 1", raw="task 1", priority="high", urgent=False,
        category="work", effort="small"))
    core.dump_task(conn, core.TaskInput(
        title="task 2", raw="task 2", priority="low", urgent=False,
        category="work", effort="small"))

    # Get task IDs
    rows = conn.execute("SELECT id FROM tasks ORDER BY created_at").fetchall()
    task_ids = [row[0] for row in rows]

    # Classify only the first task
    result = planner.classify_tasks(conn, task_ids=[task_ids[0]])

    # Should only return the first task
    assert len(result) == 1
    assert result[0]["title"] == "task 1"


def test_get_plan_proposal_with_none_date(conn):
    """get_plan_proposal with date=None uses today's date."""
    from timeopt import core, planner

    # Create a task
    core.dump_task(conn, core.TaskInput(
        title="task", raw="task", priority="high", urgent=False,
        category="work", effort="small"))

    # Call with date=None
    result = planner.get_plan_proposal(conn, [], date=None)

    # Should use today's date and return blocks or empty
    assert "blocks" in result
    assert "deferred" in result


def test_get_plan_proposal_bad_effort_config_uses_default(conn):
    """Non-integer effort_medium_min falls back to default instead of crashing."""
    from timeopt import core
    conn.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
        ("effort_medium_min", "not_a_number")
    )
    conn.commit()
    cfg = core.get_all_config(conn)
    # Create a task so the planner has something to schedule
    create_task(conn, _task("test task", "high", False))
    # Should not raise — should fall back to default 60
    result = get_plan_proposal(conn, events=[], date="2026-04-15")
    assert "blocks" in result
    assert "deferred" in result


def test_push_calendar_blocks_with_empty_blocks(conn):
    """push_calendar_blocks with no blocks returns early."""
    from timeopt import planner
    from unittest.mock import MagicMock

    # Create proposal with no blocks
    proposal = {"blocks": [], "deferred": []}
    caldav = MagicMock()

    # Should return without error
    result = planner.push_calendar_blocks(conn, proposal, "2026-04-09", caldav)

    # Should be None (returns early)
    assert result is None


def test_get_plan_proposal_bad_day_start_uses_default(tmp_path):
    """If day_start config is invalid, planning uses defaults and does not crash."""
    from timeopt import db, core, planner
    conn = db.get_connection(str(tmp_path / "test.db"))
    db.create_schema(conn)
    core.set_config(conn, "day_start", "9am_invalid")
    result = planner.get_plan_proposal(conn, [], date="2026-04-10")
    assert "blocks" in result
    assert "deferred" in result
    conn.close()
