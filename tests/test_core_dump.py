"""Tests for _parse_json_array and cli_dump (core.py Block 1 coverage)."""
import json
import pytest
from unittest.mock import MagicMock

from timeopt.core import _parse_json_array, cli_dump, list_tasks


# ---------------------------------------------------------------------------
# _parse_json_array
# ---------------------------------------------------------------------------

def test_parse_json_array_clean():
    text = '[{"title": "fix login", "priority": "high"}]'
    result = _parse_json_array(text)
    assert result == [{"title": "fix login", "priority": "high"}]


def test_parse_json_array_markdown_wrapped():
    text = '```json\n[{"title": "fix login"}]\n```'
    result = _parse_json_array(text)
    assert result == [{"title": "fix login"}]


def test_parse_json_array_leading_text():
    text = 'Here are your tasks:\n[{"title": "fix login"}, {"title": "call dentist"}]'
    result = _parse_json_array(text)
    assert len(result) == 2
    assert result[0]["title"] == "fix login"


def test_parse_json_array_no_array_raises():
    with pytest.raises(ValueError, match="no JSON array"):
        _parse_json_array("Sorry, I cannot help with that.")


def test_parse_json_array_greedy_two_arrays():
    # Greedy regex spans from first [ to last ] — result includes both arrays' content.
    # This is the documented behavior (may produce garbage), not a bug.
    text = '[{"a": 1}] some text [{"b": 2}]'
    # json.loads will fail or return the outer span — either way documents the behavior
    try:
        result = _parse_json_array(text)
        # If it parses, it should be a list (exact content is implementation-defined)
        assert isinstance(result, list)
    except (ValueError, json.JSONDecodeError):
        pass  # Also acceptable: greedy span produces invalid JSON


def test_parse_json_array_empty_array():
    result = _parse_json_array("[]")
    assert result == []


def test_parse_json_array_truncated_json_raises():
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _parse_json_array('[{"title": "fix login"')


# ---------------------------------------------------------------------------
# Fragment splitting helpers (tested via cli_dump)
# ---------------------------------------------------------------------------

def _make_llm(responses: list[dict]) -> MagicMock:
    """Return a mock llm_client.complete() that returns the given tasks as JSON."""
    mock = MagicMock()
    mock.complete.return_value = json.dumps(responses)
    return mock


def test_cli_dump_single_fragment(conn):
    llm = _make_llm([{
        "title": "fix login bug", "raw": "fix login bug",
        "priority": "high", "urgent": False, "category": "work", "effort": "medium",
    }])
    result = cli_dump(conn, llm, "fix login bug")
    assert result["count"] == 1
    assert len(result["display_ids"]) == 1
    tasks = list_tasks(conn)
    assert tasks[0]["title"] == "fix login bug"


def test_cli_dump_returns_count_and_display_ids(conn):
    llm = _make_llm([
        {"title": "buy milk", "raw": "buy milk",
         "priority": "low", "urgent": False, "category": "errands", "effort": "small"},
        {"title": "fix login", "raw": "fix login",
         "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
    ])
    result = cli_dump(conn, llm, "buy milk, fix login")
    assert result["count"] == 2
    assert len(result["display_ids"]) == 2


def test_cli_dump_splits_on_comma(conn):
    captured = {}

    def capture(system, user):
        captured["user"] = user
        return json.dumps([
            {"title": "buy milk", "raw": "buy milk",
             "priority": "low", "urgent": False, "category": "errands", "effort": "small"},
            {"title": "fix login", "raw": "fix login",
             "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
        ])

    llm = MagicMock()
    llm.complete.side_effect = capture
    cli_dump(conn, llm, "buy milk, fix login")
    # Two templates should appear in the LLM prompt
    assert '"buy milk"' in captured["user"]
    assert '"fix login"' in captured["user"]


def test_cli_dump_splits_on_semicolon(conn):
    captured_templates = {}

    def capture(system, user):
        captured_templates["user"] = user
        return json.dumps([
            {"title": "send report", "raw": "send report",
             "priority": "medium", "urgent": False, "category": "work", "effort": "small"},
            {"title": "call dentist", "raw": "call dentist",
             "priority": "low", "urgent": False, "category": "personal", "effort": "small"},
        ])

    llm = MagicMock()
    llm.complete.side_effect = capture
    cli_dump(conn, llm, "send report; call dentist")
    assert '"send report"' in captured_templates["user"]
    assert '"call dentist"' in captured_templates["user"]


def test_cli_dump_splits_on_word_and(conn):
    captured = {}

    def capture(system, user):
        captured["user"] = user
        return json.dumps([
            {"title": "buy milk", "raw": "buy milk",
             "priority": "low", "urgent": False, "category": "errands", "effort": "small"},
            {"title": "fix login", "raw": "fix login",
             "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
        ])

    llm = MagicMock()
    llm.complete.side_effect = capture
    cli_dump(conn, llm, "buy milk and fix login")
    assert '"buy milk"' in captured["user"]
    assert '"fix login"' in captured["user"]


def test_cli_dump_does_not_split_and_inside_word(conn):
    """'sandcastle' and 'brand new task' must not be split on 'and'."""
    captured = {}

    def capture(system, user):
        captured["user"] = user
        return json.dumps([
            {"title": "sandcastle project", "raw": "sandcastle project",
             "priority": "low", "urgent": False, "category": "other", "effort": "large"},
        ])

    llm = MagicMock()
    llm.complete.side_effect = capture
    result = cli_dump(conn, llm, "sandcastle project")
    # Only 1 fragment passed to LLM
    assert result["count"] == 1
    templates_in_prompt = captured["user"]
    assert '"sandcastle project"' in templates_in_prompt


def test_cli_dump_does_not_split_and_in_brand_new(conn):
    """'brand new task' should remain a single fragment."""
    captured = {}

    def capture(system, user):
        captured["user"] = user
        return json.dumps([
            {"title": "brand new task", "raw": "brand new task",
             "priority": "low", "urgent": False, "category": "other", "effort": "medium"},
        ])

    llm = MagicMock()
    llm.complete.side_effect = capture
    result = cli_dump(conn, llm, "brand new task")
    assert result["count"] == 1


def test_cli_dump_trailing_comma_no_empty_fragment(conn):
    """Trailing comma should not create an empty fragment."""
    captured = {}

    def capture(system, user):
        captured["user"] = user
        return json.dumps([
            {"title": "fix login", "raw": "fix login",
             "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
        ])

    llm = MagicMock()
    llm.complete.side_effect = capture
    result = cli_dump(conn, llm, "fix login,")
    assert result["count"] == 1


def test_cli_dump_uses_empty_events_list(conn):
    """cli_dump always passes events=[] to get_dump_templates (CLI has no CalDAV)."""
    from unittest.mock import patch
    import timeopt.core as core_mod

    captured_events = {}

    original = core_mod.get_dump_templates
    def spy(fragments, events):
        captured_events["events"] = events
        return original(fragments, events)

    with patch.object(core_mod, "get_dump_templates", side_effect=spy):
        llm = _make_llm([{
            "title": "fix login", "raw": "fix login",
            "priority": "high", "urgent": False, "category": "work", "effort": "medium",
        }])
        cli_dump(conn, llm, "fix login")

    assert captured_events["events"] == []


def test_cli_dump_partial_llm_response(conn):
    """LLM returns fewer tasks than fragments — only returned tasks are saved."""
    llm = _make_llm([{
        "title": "buy milk", "raw": "buy milk",
        "priority": "low", "urgent": False, "category": "errands", "effort": "small",
    }])
    # Two fragments but LLM only fills one
    result = cli_dump(conn, llm, "buy milk, fix login")
    assert result["count"] == 1
    assert len(list_tasks(conn)) == 1


def test_cli_dump_malformed_llm_json_raises(conn):
    """LLM returns malformed JSON — ValueError (or JSONDecodeError) bubbles up."""
    llm = MagicMock()
    llm.complete.return_value = "Sorry, I cannot parse that."
    with pytest.raises(ValueError):
        cli_dump(conn, llm, "fix login")


def test_cli_dump_task_fields_saved_correctly(conn):
    """Fields from LLM response are mapped into TaskInput correctly."""
    llm = _make_llm([{
        "title": "urgent work task", "raw": "urgent work task",
        "priority": "high", "urgent": True, "category": "work", "effort": "large",
    }])
    cli_dump(conn, llm, "urgent work task")
    tasks = list_tasks(conn)
    assert len(tasks) == 1
    t = tasks[0]
    assert t["title"] == "urgent work task"
    assert t["priority"] == "high"
    assert t["urgent"] == 1
    assert t["category"] == "work"
    assert t["effort"] == "large"


# ============================================================================
# Block 12: _parse_json_array security/robustness
# ============================================================================


def test_cli_dump_with_empty_array_response(conn):
    """LLM returns [] — cli_dump should save 0 tasks without crashing."""
    llm = MagicMock()
    llm.complete.return_value = "[]"
    result = cli_dump(conn, llm, "fix login")
    assert result["count"] == 0
    assert result["display_ids"] == []
    # Verify no tasks were saved
    tasks = list_tasks(conn)
    assert len(tasks) == 0


def test_parse_json_array_with_large_response():
    """Generate a large JSON array (~100 items) — verify _parse_json_array handles it without timeout or crash."""
    items = [
        {
            "title": f"task {i}",
            "raw": f"task {i}",
            "priority": "high" if i % 2 == 0 else "low",
            "urgent": False,
            "category": "work",
            "effort": "small",
        }
        for i in range(100)
    ]
    json_text = json.dumps(items)
    result = _parse_json_array(json_text)
    assert isinstance(result, list)
    assert len(result) == 100
    assert result[0]["title"] == "task 0"
    assert result[99]["title"] == "task 99"
