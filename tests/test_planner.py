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
