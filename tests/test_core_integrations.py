from timeopt.core import get_dump_templates, resolve_calendar_reference
from timeopt.caldav_client import CalendarEvent


MOCK_EVENTS = [
    CalendarEvent(uid="uid-1", title="Meeting with Jeff",
                  start="2026-03-28T14:00:00+00:00", end="2026-03-28T15:00:00+00:00"),
    CalendarEvent(uid="uid-2", title="Team standup",
                  start="2026-03-28T09:00:00+00:00", end="2026-03-28T09:30:00+00:00"),
]


def test_get_dump_templates_returns_schema_and_templates():
    fragments = ["fix login bug", "call dentist"]
    result = get_dump_templates(fragments, events=[])
    assert "schema" in result
    assert "templates" in result
    assert len(result["templates"]) == 2


def test_get_dump_templates_schema_appears_once():
    fragments = ["task a", "task b", "task c"]
    result = get_dump_templates(fragments, events=[])
    # Schema is a top-level key, NOT inside each template
    for t in result["templates"]:
        assert "priority" not in t or t.get("priority") == "?"
        assert "schema" not in t


def test_get_dump_templates_omits_due_fields_for_simple_tasks():
    result = get_dump_templates(["fix login bug"], events=[])
    tmpl = result["templates"][0]
    assert "due_at" not in tmpl
    assert "due_event_label" not in tmpl


def test_get_dump_templates_includes_due_at_for_time_ref():
    result = get_dump_templates(["deploy before noon"], events=[])
    tmpl = result["templates"][0]
    assert "due_at" in tmpl


def test_get_dump_templates_includes_event_label_for_calendar_ref():
    result = get_dump_templates(["prep report before meeting with Jeff"], events=MOCK_EVENTS)
    tmpl = result["templates"][0]
    assert "due_event_label" in tmpl
    assert tmpl["due_event_label"] == "meeting with Jeff"


def test_get_dump_templates_raw_and_title_prefilled():
    result = get_dump_templates(["fix login bug"], events=[])
    tmpl = result["templates"][0]
    assert tmpl["raw"] == "fix login bug"
    assert tmpl["title"] == "fix login bug"


def test_resolve_calendar_reference_finds_match():
    match = resolve_calendar_reference("meeting with Jeff", MOCK_EVENTS)
    assert match is not None
    assert match["uid"] == "uid-1"
    assert match["score"] >= 70


def test_resolve_calendar_reference_returns_none_for_no_match():
    match = resolve_calendar_reference("board meeting", [])
    assert match is None


def test_resolve_calendar_reference_picks_highest_score():
    match = resolve_calendar_reference("standup", MOCK_EVENTS)
    assert match is not None
    assert "standup" in match["title"].lower()


from timeopt.core import dump_task, dump_tasks, TaskInput


def test_dump_task_saves_and_returns_display_id(conn):
    task = TaskInput(
        title="fix login bug", raw="fix login bug",
        priority="high", urgent=False, category="work", effort="medium"
    )
    display_id = dump_task(conn, task)
    assert display_id.startswith("#1-")
    row = conn.execute("SELECT * FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    assert row is not None


def test_dump_task_auto_classifies(conn):
    from datetime import datetime, timezone, timedelta
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    task = TaskInput(
        title="overdue task", raw="overdue",
        priority="medium", urgent=False,
        category="work", effort="small", due_at=past
    )
    dump_task(conn, task)
    row = conn.execute("SELECT urgent FROM tasks WHERE title='overdue task'").fetchone()
    assert row[0] == 1  # urgency auto-upgraded


def test_dump_task_binds_calendar_event(conn):
    task = TaskInput(
        title="prep report", raw="prep report before meeting with Jeff",
        priority="high", urgent=False, category="work", effort="large",
        due_event_label="meeting with Jeff",
        due_event_uid="uid-1",
        due_event_offset_min=-30,
        due_at="2026-03-28T13:30:00+00:00",
    )
    display_id = dump_task(conn, task)
    row = conn.execute(
        "SELECT due_event_uid, due_unresolved FROM tasks WHERE display_id=?",
        (display_id,)
    ).fetchone()
    assert row["due_event_uid"] == "uid-1"
    assert row["due_unresolved"] == 0


def test_dump_tasks_saves_batch(conn):
    tasks = [
        TaskInput(title="task a", raw="a", priority="high", urgent=False,
                  category="work", effort="small"),
        TaskInput(title="task b", raw="b", priority="low", urgent=False,
                  category="personal", effort="small"),
    ]
    display_ids = dump_tasks(conn, tasks)
    assert len(display_ids) == 2
    count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    assert count == 2
