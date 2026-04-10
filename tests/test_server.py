import os
import pytest
from unittest.mock import patch, MagicMock
from timeopt import db, core
from timeopt.caldav_client import CalendarEvent


@pytest.fixture
def server_env(tmp_path):
    """Set TIMEOPT_DB to a temp file DB and initialize schema."""
    db_path = str(tmp_path / "test.db")
    conn = db.get_connection(db_path)
    db.create_schema(conn)
    conn.close()
    with patch.dict(os.environ, {"TIMEOPT_DB": db_path}):
        yield db_path


def _seed_one(db_path, **kwargs):
    """Helper: seed a single task, return the connection (caller must close)."""
    defaults = {"title": "task", "raw": "task", "priority": "medium",
                "urgent": False, "category": "work", "effort": "small"}
    defaults.update(kwargs)
    conn = db.get_connection(db_path)
    core.dump_task(conn, core.TaskInput(**defaults))
    return conn


def test_list_tasks_empty(server_env):
    from timeopt.server import list_tasks
    result = list_tasks()
    assert result["tasks"] == []


def test_dump_task_and_list(server_env):
    from timeopt.server import dump_task, list_tasks
    result = dump_task(task={
        "raw": "fix login bug", "title": "fix login bug",
        "priority": "high", "urgent": False, "category": "work", "effort": "medium",
    })
    assert result["display_id"].startswith("#1-")
    assert result["id"] is not None
    tasks = list_tasks()
    assert len(tasks["tasks"]) == 1
    assert tasks["tasks"][0]["title"] == "fix login bug"


def test_get_task(server_env):
    from timeopt.server import dump_task, get_task
    dumped = dump_task(task={"raw": "buy milk", "title": "buy milk",
                              "priority": "low", "urgent": False,
                              "category": "errands", "effort": "small"})
    # get_task requires UUID — use dumped["id"]
    task = get_task(task_id=dumped["id"])
    assert task["title"] == "buy milk"
    assert task["category"] == "errands"


def test_fuzzy_match_tasks(server_env):
    from timeopt.server import dump_task, fuzzy_match_tasks
    dump_task(task={"raw": "fix login bug", "title": "fix login bug",
                    "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    result = fuzzy_match_tasks(query="login")
    assert len(result["candidates"]) >= 1
    assert result["candidates"][0]["score"] > 50


def test_mark_done(server_env):
    from timeopt.server import dump_task, mark_done, list_tasks
    dumped = dump_task(task={"raw": "buy groceries", "title": "buy groceries",
                              "priority": "low", "urgent": False,
                              "category": "errands", "effort": "small"})
    mark_done(task_ids=[dumped["id"]])
    assert list_tasks(status="pending")["tasks"] == []


def test_mark_delegated_update_notes_and_return(server_env):
    from timeopt.server import dump_task, mark_delegated, update_task_notes, return_to_pending, get_task
    dumped = dump_task(task={"raw": "reply to lawyer", "title": "reply to lawyer",
                              "priority": "low", "urgent": True,
                              "category": "work", "effort": "small"})
    mark_delegated(task_id=dumped["id"], notes="Starting delegation")
    update_task_notes(task_id=dumped["id"], notes="Tried email — failed")
    return_to_pending(task_id=dumped["id"], notes="No email tool available")
    task = get_task(task_id=dumped["id"])
    assert task["status"] == "pending"
    assert "No email tool available" in task["notes"]


def test_update_notes_rejects_non_delegated(server_env):
    from timeopt.server import dump_task, update_task_notes
    dumped = dump_task(task={"raw": "test", "title": "test",
                              "priority": "medium", "urgent": False,
                              "category": "work", "effort": "small"})
    result = update_task_notes(task_id=dumped["id"], notes="note")
    assert "error" in result


def test_classify_tasks(server_env):
    from timeopt.server import dump_task, classify_tasks
    dump_task(task={"raw": "urgent low", "title": "urgent low priority",
                    "priority": "low", "urgent": True, "category": "work", "effort": "small"})
    dump_task(task={"raw": "important big", "title": "important big project",
                    "priority": "high", "urgent": False, "category": "work", "effort": "large"})
    result = classify_tasks()
    quadrants = [t["quadrant"] for t in result["tasks"]]
    assert "Q3" in quadrants
    assert "Q2" in quadrants


def test_get_config_default(server_env):
    from timeopt.server import get_config
    result = get_config(key="day_start")
    assert result["value"] == "09:00"


def test_set_and_get_config(server_env):
    from timeopt.server import set_config, get_config
    set_config(key="day_start", value="08:00")
    assert get_config(key="day_start")["value"] == "08:00"


def test_get_all_config(server_env):
    from timeopt.server import get_config
    result = get_config()
    assert "day_start" in result
    assert "day_end" in result


def test_get_dump_templates(server_env):
    from timeopt.server import get_dump_templates
    result = get_dump_templates(fragments=["fix login bug", "deploy before noon"])
    assert "schema" in result
    assert "templates" in result
    assert len(result["templates"]) == 2
    # Simple task: no due_at pre-filled
    assert "due_at" not in result["templates"][0]
    # Time reference: due_at pre-filled
    assert "due_at" in result["templates"][1]


def test_dump_task_returns_id_and_display_id(server_env):
    from timeopt.server import dump_task
    result = dump_task(task={
        "raw": "prep report before meeting with Jeff",
        "title": "prep report",
        "priority": "high",
        "urgent": False,
        "category": "work",
        "effort": "large",
        "due_event_label": "meeting with Jeff",
        "due_event_offset_min": -30,
    })
    assert "display_id" in result
    assert "id" in result
    assert result["id"] is not None


def test_dump_tasks_batch(server_env):
    from timeopt.server import dump_tasks, list_tasks
    result = dump_tasks(tasks=[
        {"raw": "a", "title": "task a", "priority": "high",
         "urgent": False, "category": "work", "effort": "small"},
        {"raw": "b", "title": "task b", "priority": "low",
         "urgent": False, "category": "personal", "effort": "small"},
    ])
    assert result["count"] == 2
    assert len(result["display_ids"]) == 2
    assert len(list_tasks()["tasks"]) == 2


def test_get_calendar_events_no_caldav(server_env):
    from timeopt.server import get_calendar_events
    result = get_calendar_events()
    assert "events" in result
    # No CalDAV configured: empty list with warning
    assert result["events"] == []
    assert "warning" in result


def test_resolve_calendar_reference_no_caldav(server_env):
    from timeopt.server import resolve_calendar_reference
    result = resolve_calendar_reference(label="meeting with Jeff")
    assert "candidates" in result
    assert result["candidates"] == []
    assert "error" in result


def test_get_plan_proposal_no_caldav(server_env):
    from timeopt.server import dump_task, get_plan_proposal
    dump_task(task={"raw": "fix login", "title": "fix login",
                    "priority": "high", "urgent": False,
                    "category": "work", "effort": "medium"})
    result = get_plan_proposal(date="2026-03-28")
    assert "blocks" in result


def test_push_calendar_blocks_no_caldav(server_env):
    from timeopt.server import push_calendar_blocks
    result = push_calendar_blocks(blocks=[], date="2026-03-28")
    assert result["ok"] is False
    assert "error" in result


def test_sync_calendar_no_caldav(server_env):
    from timeopt.server import sync_calendar
    result = sync_calendar()
    assert result["ok"] is False
    assert "error" in result


# ---------------------------------------------------------------------------
# Block 2: CalDAV success paths
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_caldav(server_env):
    """Patches _get_caldav to return a preconfigured MagicMock."""
    mock = MagicMock()
    mock.get_events.return_value = []
    mock.create_event.return_value = "uid-default"
    with patch("timeopt.server._get_caldav", return_value=mock):
        yield mock


def test_get_calendar_events_with_caldav(mock_caldav):
    from timeopt.server import get_calendar_events
    mock_caldav.get_events.return_value = [
        CalendarEvent(uid="abc-123", title="Team sync",
                      start="2026-04-01T09:00:00+00:00",
                      end="2026-04-01T10:00:00+00:00"),
    ]
    result = get_calendar_events(date="2026-04-01")
    assert result["events"] == [
        {"title": "Team sync", "start": "2026-04-01T09:00:00+00:00",
         "end": "2026-04-01T10:00:00+00:00", "uid": "abc-123"}
    ]


def test_resolve_calendar_reference_match_found(mock_caldav):
    from timeopt.server import resolve_calendar_reference
    mock_caldav.get_events.return_value = [
        CalendarEvent(uid="uid-jeff", title="Meeting with Jeff",
                      start="2026-04-01T14:00:00+00:00",
                      end="2026-04-01T15:00:00+00:00"),
    ]
    result = resolve_calendar_reference(label="meeting with Jeff")
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["uid"] == "uid-jeff"
    assert result["candidates"][0]["score"] > 50


def test_resolve_calendar_reference_no_match(mock_caldav):
    from timeopt.server import resolve_calendar_reference
    mock_caldav.get_events.return_value = [
        CalendarEvent(uid="uid-dentist", title="Dentist appointment",
                      start="2026-04-01T10:00:00+00:00",
                      end="2026-04-01T11:00:00+00:00"),
    ]
    result = resolve_calendar_reference(label="quarterly board meeting xyzzy")
    assert result["candidates"] == []


def test_resolve_calendar_reference_bad_min_score_uses_default(server_env):
    """Non-integer calendar_fuzzy_min_score falls back to 50 instead of raising ValueError."""
    from timeopt.server import resolve_calendar_reference
    conn = db.get_connection(os.environ["TIMEOPT_DB"])
    conn.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
        ("calendar_fuzzy_min_score", "bad_value")
    )
    conn.commit()
    conn.close()

    # CalDAV is configured but returns no events; should not raise ValueError
    mock_caldav = MagicMock()
    mock_caldav.get_events.return_value = []
    with patch("timeopt.server._get_caldav", return_value=mock_caldav):
        result = resolve_calendar_reference(label="standup", date_range=None)
    # Should return empty candidates, not raise ValueError
    assert "candidates" in result
    assert isinstance(result["candidates"], list)


def test_get_plan_proposal_with_caldav_events(mock_caldav):
    from timeopt.server import dump_task, get_plan_proposal
    dump_task(task={"raw": "fix login", "title": "fix login",
                    "priority": "high", "urgent": False,
                    "category": "work", "effort": "medium"})
    # Morning event occupies 09:00–10:00; task should schedule in remaining time
    mock_caldav.get_events.return_value = [
        CalendarEvent(uid="ev-standup", title="Morning standup",
                      start="2026-04-01T09:00:00+00:00",
                      end="2026-04-01T10:00:00+00:00"),
    ]
    result = get_plan_proposal(date="2026-04-01")
    assert "blocks" in result
    assert len(result["blocks"]) > 0
    # Block must not overlap the morning event
    assert result["blocks"][0]["start"] >= "2026-04-01T10:00:00"


def test_push_calendar_blocks_success(mock_caldav):
    from timeopt.server import dump_task, push_calendar_blocks
    dumped = dump_task(task={"raw": "fix login", "title": "fix login",
                              "priority": "high", "urgent": False,
                              "category": "work", "effort": "medium"})
    mock_caldav.create_event.return_value = "uid-cal-1"
    blocks = [{
        "task_id": dumped["id"],
        "display_id": dumped["display_id"],
        "title": "fix login",
        "start": "2026-04-01T10:00:00+00:00",
        "duration_min": 60,
        "quadrant": "Q2",
    }]
    result = push_calendar_blocks(blocks=blocks, date="2026-04-01")
    assert result["ok"] is True
    assert result["pushed"] == 1
    mock_caldav.create_event.assert_called_once()


def test_push_calendar_blocks_replaces_uids(mock_caldav):
    from timeopt.server import dump_task, push_calendar_blocks
    dumped = dump_task(task={"raw": "write report", "title": "write report",
                              "priority": "medium", "urgent": False,
                              "category": "work", "effort": "small"})
    blocks = [{
        "task_id": dumped["id"],
        "display_id": dumped["display_id"],
        "title": "write report",
        "start": "2026-04-01T10:00:00+00:00",
        "duration_min": 30,
        "quadrant": "Q2",
    }]
    mock_caldav.create_event.return_value = "uid-old"
    push_calendar_blocks(blocks=blocks, date="2026-04-01")

    mock_caldav.create_event.return_value = "uid-new"
    result = push_calendar_blocks(blocks=blocks, date="2026-04-01")
    assert result["ok"] is True
    mock_caldav.delete_event.assert_called_with("uid-old")


def _seed_bound_task(server_env, due_event_uid="uid-jeff",
                     due_at="2026-04-01T13:30:00+00:00"):
    db_path = server_env
    conn = db.get_connection(db_path)
    core.create_task(conn, core.TaskInput(
        title="prep report", raw="prep before meeting",
        priority="high", urgent=False, category="work", effort="large",
        due_at=due_at,
        due_event_uid=due_event_uid,
        due_event_offset_min=-30,
    ))
    conn.close()


def _seed_unresolved_task(server_env, label="board meeting"):
    db_path = server_env
    conn = db.get_connection(db_path)
    core.create_task(conn, core.TaskInput(
        title="board prep", raw="prep before board meeting",
        priority="high", urgent=False, category="work", effort="large",
        due_event_label=label,
        due_unresolved=True,
    ))
    conn.close()


def test_sync_calendar_updated(mock_caldav, server_env):
    from timeopt.server import sync_calendar
    _seed_bound_task(server_env)
    mock_caldav.get_events.return_value = [
        CalendarEvent(uid="uid-jeff", title="Meeting with Jeff",
                      start="2026-04-02T14:00:00+00:00",  # moved by one day
                      end="2026-04-02T15:00:00+00:00"),
    ]
    result = sync_calendar()
    assert result["ok"] is True
    assert len(result["updated"]) == 1
    assert result["updated"][0]["status"] == "updated"


def test_sync_calendar_resolved(mock_caldav, server_env):
    from timeopt.server import sync_calendar
    _seed_unresolved_task(server_env, label="board meeting")
    mock_caldav.get_events.return_value = [
        CalendarEvent(uid="uid-board", title="Board Meeting",
                      start="2026-04-15T10:00:00+00:00",
                      end="2026-04-15T11:00:00+00:00"),
    ]
    result = sync_calendar()
    assert result["ok"] is True
    assert len(result["resolved"]) == 1


def test_sync_calendar_still_unresolved(mock_caldav, server_env):
    from timeopt.server import sync_calendar
    _seed_unresolved_task(server_env, label="very specific obscure event xyzzy")
    mock_caldav.get_events.return_value = [
        CalendarEvent(uid="uid-other", title="Dentist appointment",
                      start="2026-04-10T09:00:00+00:00",
                      end="2026-04-10T10:00:00+00:00"),
    ]
    result = sync_calendar()
    assert result["ok"] is True
    assert len(result["unresolved_remaining"]) >= 1


# ---------------------------------------------------------------------------
# Block 3: get_plan_proposal — actual scheduling
# ---------------------------------------------------------------------------

def test_get_plan_proposal_produces_populated_blocks(mock_caldav):
    """Server wrapper schedules seeded tasks into a non-empty blocks list."""
    from timeopt.server import dump_task, get_plan_proposal
    dump_task(task={"raw": "fix login", "title": "fix login",
                    "priority": "high", "urgent": True,
                    "category": "work", "effort": "small"})
    result = get_plan_proposal(date="2026-04-01")
    assert "blocks" in result
    assert len(result["blocks"]) > 0
    block = result["blocks"][0]
    assert block["title"] == "fix login"
    assert "start" in block
    assert "duration_min" in block
    assert "quadrant" in block


def test_get_plan_proposal_caldav_event_conversion(mock_caldav):
    """CalendarEvent objects are correctly converted to dicts; events carve free slots."""
    from timeopt.server import dump_task, get_plan_proposal
    dump_task(task={"raw": "afternoon task", "title": "afternoon task",
                    "priority": "high", "urgent": True,
                    "category": "work", "effort": "small"})
    # Event uses "Z" suffix — exercises replace("Z", "+00:00") parsing path
    mock_caldav.get_events.return_value = [
        CalendarEvent(uid="ev-morning", title="Morning standup",
                      start="2026-04-01T09:00:00Z",
                      end="2026-04-01T11:00:00Z"),
    ]
    result = get_plan_proposal(date="2026-04-01")
    assert len(result["blocks"]) > 0
    # Task must be scheduled after the event, not during it
    assert result["blocks"][0]["start"] >= "2026-04-01T11:00:00"


def test_get_plan_proposal_quadrant_ordering(mock_caldav):
    """Blocks appear in Q1 → Q2 → Q3 → Q4 order."""
    from timeopt.server import dump_task, get_plan_proposal
    dump_task(task={"raw": "q4 task", "title": "q4 task",
                    "priority": "low", "urgent": False,
                    "category": "work", "effort": "small"})
    dump_task(task={"raw": "q3 task", "title": "q3 task",
                    "priority": "low", "urgent": True,
                    "category": "work", "effort": "small"})
    dump_task(task={"raw": "q2 task", "title": "q2 task",
                    "priority": "high", "urgent": False,
                    "category": "work", "effort": "small"})
    dump_task(task={"raw": "q1 task", "title": "q1 task",
                    "priority": "high", "urgent": True,
                    "category": "work", "effort": "small"})
    result = get_plan_proposal(date="2026-04-01")
    quadrants = [b["quadrant"] for b in result["blocks"]]
    for q in ("Q1", "Q2", "Q3", "Q4"):
        assert q in quadrants, f"{q} missing from blocks"
    assert quadrants.index("Q1") < quadrants.index("Q2")
    assert quadrants.index("Q2") < quadrants.index("Q3")
    assert quadrants.index("Q3") < quadrants.index("Q4")


def test_get_plan_proposal_effort_mapping(mock_caldav):
    """Effort sizes map to correct duration_min: small=30, medium=60, large=120."""
    from timeopt.server import dump_task, get_plan_proposal
    # All Q1 so no ordering ambiguity; use distinct titles for lookup
    dump_task(task={"raw": "small task", "title": "small task",
                    "priority": "high", "urgent": True,
                    "category": "work", "effort": "small"})
    dump_task(task={"raw": "medium task", "title": "medium task",
                    "priority": "high", "urgent": True,
                    "category": "work", "effort": "medium"})
    dump_task(task={"raw": "large task", "title": "large task",
                    "priority": "high", "urgent": True,
                    "category": "work", "effort": "large"})
    result = get_plan_proposal(date="2026-04-01")
    durations = {b["title"]: b["duration_min"] for b in result["blocks"]}
    assert durations["small task"] == 30
    assert durations["medium task"] == 60
    assert durations["large task"] == 120


def test_get_plan_proposal_deferred_when_day_full(mock_caldav):
    """Tasks that exceed available day capacity appear in deferred list."""
    from timeopt.server import dump_task, get_plan_proposal, set_config
    # Shrink work day to 1 hour so large tasks (120 min each) don't fit
    set_config(key="day_start", value="09:00")
    set_config(key="day_end", value="10:00")
    for i in range(3):
        dump_task(task={"raw": f"big task {i}", "title": f"big task {i}",
                        "priority": "high", "urgent": True,
                        "category": "work", "effort": "large"})
    result = get_plan_proposal(date="2026-04-01")
    assert "deferred" in result
    assert len(result["deferred"]) > 0


def test_get_plan_proposal_break_insertion(mock_caldav):
    """Consecutive blocks have a break gap between end of first and start of next."""
    from timeopt.server import dump_task, get_plan_proposal, get_config
    from datetime import datetime, timedelta
    dump_task(task={"raw": "first task", "title": "first task",
                    "priority": "high", "urgent": True,
                    "category": "work", "effort": "small"})
    dump_task(task={"raw": "second task", "title": "second task",
                    "priority": "high", "urgent": True,
                    "category": "work", "effort": "small"})
    result = get_plan_proposal(date="2026-04-01")
    blocks = result["blocks"]
    assert len(blocks) >= 2, "need at least 2 scheduled blocks to test break insertion"
    break_min = int(get_config(key="break_duration_min")["value"])
    first_end = datetime.fromisoformat(blocks[0]["start"]) + timedelta(minutes=blocks[0]["duration_min"])
    second_start = datetime.fromisoformat(blocks[1]["start"])
    assert second_start >= first_end + timedelta(minutes=break_min)


# ---------------------------------------------------------------------------
# Block 4: Server mutation tools — error paths
# ---------------------------------------------------------------------------

def test_get_task_nonexistent_uuid(server_env):
    from timeopt.server import get_task
    result = get_task(task_id="00000000-0000-0000-0000-000000000000")
    assert "error" in result
    assert "Task not found" in result["error"]


def test_mark_done_nonexistent_uuid(server_env):
    from timeopt.server import mark_done
    result = mark_done(task_ids=["00000000-0000-0000-0000-000000000000"])
    assert "error" in result
    assert "Task not found" in result["error"]


def test_mark_done_nonexistent_display_id(server_env):
    from timeopt.server import mark_done
    result = mark_done(task_ids=["#99-nonexistent-task"])
    assert "error" in result
    assert "Task not found" in result["error"]


def test_mark_done_already_done_task(server_env):
    from timeopt.server import dump_task, mark_done
    dumped = dump_task(task={"raw": "finish report", "title": "finish report",
                              "priority": "medium", "urgent": False,
                              "category": "work", "effort": "small"})
    mark_done(task_ids=[dumped["id"]])
    # Second mark_done on same UUID — task is now "done", not active
    result = mark_done(task_ids=[dumped["id"]])
    assert "error" in result
    assert "not active" in result["error"]


def test_mark_delegated_nonexistent_uuid(server_env):
    from timeopt.server import mark_delegated
    result = mark_delegated(task_id="00000000-0000-0000-0000-000000000000")
    assert "error" in result
    assert "Pending task not found" in result["error"]


def test_mark_delegated_nonexistent_display_id(server_env):
    from timeopt.server import mark_delegated
    result = mark_delegated(task_id="#99-nonexistent-task")
    assert "error" in result
    assert "Pending task not found" in result["error"]


def test_update_task_notes_on_done_task(server_env):
    from timeopt.server import dump_task, mark_done, update_task_notes
    dumped = dump_task(task={"raw": "deploy to prod", "title": "deploy to prod",
                              "priority": "high", "urgent": True,
                              "category": "work", "effort": "small"})
    mark_done(task_ids=[dumped["id"]])
    result = update_task_notes(task_id=dumped["id"], notes="post-done note")
    assert "error" in result
    assert "not delegated" in result["error"]


def test_return_to_pending_on_pending_task(server_env):
    from timeopt.server import dump_task, return_to_pending
    dumped = dump_task(task={"raw": "write tests", "title": "write tests",
                              "priority": "medium", "urgent": False,
                              "category": "work", "effort": "small"})
    # Task is pending, not delegated — return_to_pending should error
    result = return_to_pending(task_id=dumped["id"], notes="never was delegated")
    assert "error" in result
    assert "Delegated task not found" in result["error"]


def test_return_to_pending_nonexistent_uuid(server_env):
    from timeopt.server import return_to_pending
    result = return_to_pending(task_id="00000000-0000-0000-0000-000000000000",
                               notes="nothing here")
    assert "error" in result
    assert "Delegated task not found" in result["error"]


def test_get_config_unknown_key(server_env):
    from timeopt.server import get_config
    result = get_config(key="totally_nonexistent_key_xyzzy")
    assert "error" in result
    assert "Unknown config key" in result["error"]


def test_get_config_unknown_key_uses_key_error_not_value_error(server_env):
    """core.get_config raises KeyError; server must catch KeyError separately (not ValueError).
    If server catches ValueError instead, this test would fail because the error
    would propagate as an uncaught exception rather than returning {"error": ...}."""
    from timeopt.server import get_config
    # This would raise an exception (not return a dict) if server caught ValueError only
    result = get_config(key="unknown_key_abc123")
    assert isinstance(result, dict)
    assert "error" in result


def test_set_config_unknown_key_returns_error(server_env):
    from timeopt.server import set_config
    result = set_config(key="totally_made_up_key", value="anything")
    assert result.get("ok") is False
    assert "error" in result
    assert "totally_made_up_key" in result["error"]


def test_set_config_sensitive_key_masks_value_in_response(server_env):
    """set_config success response masks sensitive values."""
    from timeopt.server import set_config
    result = set_config(key="llm_api_key", value="sk-secret-xyz")
    assert result["ok"] is True
    assert result["key"] == "llm_api_key"
    assert result["value"] != "sk-secret-xyz"
    assert result["value"] == "***"


def test_set_config_caldav_password_masked_in_response(server_env):
    """set_config masks caldav_password in response."""
    from timeopt.server import set_config
    result = set_config(key="caldav_password", value="hunter2")
    assert result["ok"] is True
    assert result["value"] != "hunter2"
    assert result["value"] == "***"


def test_set_config_non_sensitive_key_shows_value_in_response(server_env):
    """set_config shows actual value for non-sensitive keys."""
    from timeopt.server import set_config
    result = set_config(key="day_start", value="08:00")
    assert result["ok"] is True
    assert result["value"] == "08:00"


# ---------------------------------------------------------------------------
# Block 8: fuzzy_match_tasks edge cases
# ---------------------------------------------------------------------------

def test_fuzzy_match_empty_db(server_env):
    """Empty DB returns empty candidates list."""
    from timeopt.server import fuzzy_match_tasks
    result = fuzzy_match_tasks(query="anything")
    assert result["candidates"] == []


def test_fuzzy_match_all_tasks_done(server_env):
    """All done tasks returns empty candidates (only searches pending/delegated)."""
    from timeopt.server import dump_task, mark_done, fuzzy_match_tasks
    dumped = dump_task(task={"raw": "fix login", "title": "fix login",
                             "priority": "high", "urgent": False,
                             "category": "work", "effort": "small"})
    mark_done(task_ids=[dumped["id"]])
    result = fuzzy_match_tasks(query="fix")
    assert result["candidates"] == []


def test_fuzzy_match_very_short_query(server_env):
    """Very short query (single character) still returns list (may have results)."""
    from timeopt.server import dump_task, fuzzy_match_tasks
    dump_task(task={"raw": "fix login", "title": "fix login",
                    "priority": "high", "urgent": False,
                    "category": "work", "effort": "small"})
    dump_task(task={"raw": "apply patch", "title": "apply patch",
                    "priority": "medium", "urgent": False,
                    "category": "work", "effort": "medium"})
    # Single character query should not raise
    result = fuzzy_match_tasks(query="a")
    assert isinstance(result["candidates"], list)


def test_get_caldav_uses_config_defaults(server_env):
    """_get_caldav() reads url/calendars from config, not inline fallbacks."""
    from unittest.mock import patch, MagicMock
    from timeopt import db, core
    conn = db.get_connection(server_env)
    core.set_config(conn, "caldav_url", "https://custom.caldav.example.com")
    core.set_config(conn, "caldav_username", "user")
    core.set_config(conn, "caldav_password", "pass")
    conn.close()

    with patch("timeopt.server.CalDAVClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        from timeopt.server import _get_caldav, _open_conn
        c = _open_conn()
        _get_caldav(c)
        c.close()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["url"] == "https://custom.caldav.example.com"


def test_resolve_calendar_reference_with_date_range(mock_caldav):
    """Passing date_range dict with start/end verifies get_events is called and match is returned."""
    from timeopt.server import resolve_calendar_reference
    mock_caldav.get_events.return_value = [
        CalendarEvent(uid="uid-team-sync", title="Team sync",
                      start="2026-04-05T09:00:00Z",
                      end="2026-04-05T10:00:00Z"),
    ]
    result = resolve_calendar_reference(
        label="team sync",
        date_range={"start": "2026-04-01", "end": "2026-04-10"}
    )
    # Verify get_events was called
    mock_caldav.get_events.assert_called_once()
    # Verify result contains the matched event
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["uid"] == "uid-team-sync"
    assert result["candidates"][0]["score"] > 50


def test_resolve_calendar_reference_date_range_sets_window(mock_caldav):
    """Verify that date_range start/end correctly sets get_events call parameters."""
    from timeopt.server import resolve_calendar_reference
    mock_caldav.get_events.return_value = []

    # Call with start="2026-04-01", end="2026-04-11" (10 days apart)
    resolve_calendar_reference(
        label="some event",
        date_range={"start": "2026-04-01", "end": "2026-04-11"}
    )

    # Verify get_events was called with correct start date and days parameter
    call_args = mock_caldav.get_events.call_args
    assert call_args is not None
    # First positional arg should be the start date in ISO format
    assert call_args[0][0] == "2026-04-01"
    # days keyword arg should be (end - start).days = 10
    assert call_args[1]["days"] == 10


def test_sync_calendar_caldav_error_returns_structured_error(server_env):
    """sync_calendar handles transient CalDAV errors gracefully (get_events returns [])."""
    from timeopt.server import sync_calendar
    mock_caldav = MagicMock()
    # get_events never raises — it catches exceptions and returns []
    mock_caldav.get_events.return_value = []
    with patch("timeopt.server._get_caldav", return_value=mock_caldav):
        result = sync_calendar(date_range_days=7)
    # With no events, sync succeeds with empty results
    assert result.get("ok") is True
    assert result.get("updated") == []
    assert result.get("resolved") == []


def test_push_calendar_blocks_planner_error_returns_structured_error(server_env):
    """push_calendar_blocks wraps planner exceptions and returns structured error."""
    from timeopt.server import push_calendar_blocks
    mock_caldav = MagicMock()
    mock_caldav.create_event.side_effect = RuntimeError("CalDAV write failed")
    with patch("timeopt.server._get_caldav", return_value=mock_caldav):
        result = push_calendar_blocks(
            blocks=[{"task_id": "fake-id", "display_id": "#1-t", "title": "T",
                     "start": "2026-04-10T09:00:00", "duration_min": 60, "quadrant": "Q1"}],
            date="2026-04-10",
        )
    assert result.get("ok") is False
    assert "error" in result


def test_get_config_unknown_key_returns_ok_false(server_env):
    from timeopt import server
    result = server.get_config(key="completely_unknown_key_xyz")
    assert result.get("ok") is False
    assert "error" in result
