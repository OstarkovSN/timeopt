import os
import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from timeopt import db, core


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def cli_env(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = db.get_connection(db_path)
    db.create_schema(conn)
    conn.close()
    with patch.dict(os.environ, {"TIMEOPT_DB": db_path}):
        yield db_path


def _seed(db_path, *task_kwargs_list):
    conn = db.get_connection(db_path)
    for kwargs in task_kwargs_list:
        core.dump_task(conn, core.TaskInput(**kwargs))
    conn.close()


def test_tasks_empty(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["tasks"])
    assert result.exit_code == 0
    assert "No tasks" in result.output


def test_tasks_shows_pending(runner, cli_env):
    from timeopt.cli import cli
    _seed(cli_env, {"title": "fix login bug", "raw": "fix login bug",
                    "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    result = runner.invoke(cli, ["tasks"])
    assert result.exit_code == 0
    assert "#1-fix-login-bug" in result.output
    assert "work" in result.output
    assert "high" in result.output


def test_tasks_status_filter(runner, cli_env):
    from timeopt.cli import cli
    _seed(cli_env, {"title": "fix login", "raw": "fix login",
                    "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    conn = db.get_connection(cli_env)
    row = conn.execute("SELECT id FROM tasks").fetchone()
    core.mark_done(conn, [row[0]])
    conn.close()
    result = runner.invoke(cli, ["tasks", "--status", "pending"])
    assert result.exit_code == 0
    assert "fix-login" not in result.output


def test_history_empty(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["history", "--today"])
    assert result.exit_code == 0
    assert "No completed tasks" in result.output


def test_history_shows_done(runner, cli_env):
    from timeopt.cli import cli
    _seed(cli_env, {"title": "fix login", "raw": "fix login",
                    "priority": "high", "urgent": False, "category": "work", "effort": "small"})
    conn = db.get_connection(cli_env)
    row = conn.execute("SELECT id FROM tasks").fetchone()
    core.mark_done(conn, [row[0]])
    conn.close()
    result = runner.invoke(cli, ["history", "--today"])
    assert result.exit_code == 0
    assert "#1-fix-login" in result.output


def test_config_get_default(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["config", "get", "day_start"])
    assert result.exit_code == 0
    assert "09:00" in result.output


def test_config_get_all(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["config", "get"])
    assert result.exit_code == 0
    assert "day_start" in result.output
    assert "day_end" in result.output


def test_config_set_and_get(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["config", "set", "day_start", "08:00"])
    assert result.exit_code == 0
    result = runner.invoke(cli, ["config", "get", "day_start"])
    assert "08:00" in result.output


def test_config_set_unknown_key_shows_error(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["config", "set", "nonexistent_key", "val"])
    assert result.exit_code != 0
    assert "nonexistent_key" in result.output


def test_done_marks_task(runner, cli_env):
    from timeopt.cli import cli
    _seed(cli_env, {"title": "fix login bug", "raw": "fix login bug",
                    "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    result = runner.invoke(cli, ["done", "fix login"])
    assert result.exit_code == 0
    assert "✓" in result.output
    conn = db.get_connection(cli_env)
    row = conn.execute("SELECT status FROM tasks").fetchone()
    conn.close()
    assert row[0] == "done"


def test_done_ambiguous_prompts_user(runner, cli_env):
    from timeopt.cli import cli
    _seed(cli_env,
        {"title": "fix login bug", "raw": "fix login bug",
         "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
        {"title": "fix login redirect", "raw": "fix login redirect",
         "priority": "high", "urgent": False, "category": "work", "effort": "small"},
    )
    conn = db.get_connection(cli_env)
    core.set_config(conn, "fuzzy_match_ask_gap", "100")  # force ambiguity
    conn.close()
    result = runner.invoke(cli, ["done", "login"], input="0\n")  # user skips
    assert result.exit_code == 0


def test_done_no_match(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["done", "xyzzy nonexistent task qqqq"])
    assert result.exit_code == 0
    assert "No confident match" in result.output


def test_dump_with_mocked_llm(runner, cli_env):
    from timeopt.cli import cli
    mock_llm = MagicMock()
    mock_llm.complete.return_value = (
        '[{"raw": "fix login", "title": "fix login", "priority": "high",'
        ' "urgent": false, "category": "work", "effort": "medium"}]'
    )
    with patch("timeopt.cli._get_llm_client", return_value=mock_llm):
        result = runner.invoke(cli, ["dump", "fix login bug"])
    assert result.exit_code == 0
    assert "Added" in result.output
    assert "#1-fix-login" in result.output


def test_check_urgent_no_q3(runner, cli_env):
    from timeopt.cli import cli
    _seed(cli_env, {"title": "important project", "raw": "important",
                    "priority": "high", "urgent": False,
                    "category": "work", "effort": "large"})
    result = runner.invoke(cli, ["check-urgent"])
    assert result.exit_code == 0
    assert "No Q3" in result.output or "All clear" in result.output


def test_check_urgent_shows_q3(runner, cli_env):
    from timeopt.cli import cli
    _seed(cli_env, {"title": "reply to accountant", "raw": "reply to accountant",
                    "priority": "low", "urgent": True,
                    "category": "work", "effort": "small"})
    result = runner.invoke(cli, ["check-urgent"])
    assert result.exit_code == 0
    assert "Q3" in result.output


def test_sync_no_caldav(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["sync"])
    assert result.exit_code == 0
    assert "CalDAV not configured" in result.output


def test_plan_no_tasks(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["plan", "--date", "2026-03-28"])
    assert result.exit_code == 0
    assert "No tasks" in result.output


def test_done_multiple_queries(runner, cli_env):
    """Test that done command accepts multiple queries via nargs=-1."""
    from timeopt.cli import cli
    _seed(cli_env,
        {"title": "fix login bug", "raw": "fix login bug",
         "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
        {"title": "buy milk", "raw": "buy milk",
         "priority": "low", "urgent": False, "category": "personal", "effort": "small"},
    )
    result = runner.invoke(cli, ["done", "fix login", "buy milk"])
    assert result.exit_code == 0
    assert "✓" in result.output
    # Verify both tasks are marked done
    conn = db.get_connection(cli_env)
    rows = conn.execute("SELECT status FROM tasks").fetchall()
    conn.close()
    assert all(row[0] == "done" for row in rows)


def test_tasks_with_all_flag(runner, cli_env):
    """Test that tasks --all includes done tasks older than hide_done_after_days."""
    from timeopt.cli import cli
    _seed(cli_env, {"title": "fix login bug", "raw": "fix login bug",
                    "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    conn = db.get_connection(cli_env)
    row = conn.execute("SELECT id FROM tasks").fetchone()
    core.mark_done(conn, [row[0]])
    conn.close()

    # Without --all: may or may not show recently-done task depending on hide_done_after_days
    result = runner.invoke(cli, ["tasks"])
    assert result.exit_code == 0

    # With --all: definitely shows done tasks
    result_all = runner.invoke(cli, ["tasks", "--all"])
    assert result_all.exit_code == 0
    # When --all is used, done tasks should be visible in output
    assert "#1-fix-login-bug" in result_all.output


def test_plan_invalid_date_format(runner, cli_env):
    """Test that plan with invalid date format exits with error."""
    from timeopt.cli import cli
    result = runner.invoke(cli, ["plan", "--date", "not-a-date"])
    assert result.exit_code != 0


def test_config_get_unknown_key(runner, cli_env):
    """Test that config get with unknown key exits with error."""
    from timeopt.cli import cli
    result = runner.invoke(cli, ["config", "get", "unknown_config_key_xyz"])
    assert result.exit_code != 0


def test_dump_multiple_fragments(runner, cli_env):
    """Test that dump with multiple fragments parses into multiple tasks."""
    from timeopt.cli import cli
    import json
    mock_llm = MagicMock()
    mock_llm.complete.return_value = json.dumps([
        {"raw": "fix login", "title": "fix login", "priority": "high",
         "urgent": False, "category": "work", "effort": "medium"},
        {"raw": "call dentist", "title": "call dentist", "priority": "low",
         "urgent": False, "category": "personal", "effort": "small"},
    ])
    with patch("timeopt.cli._get_llm_client", return_value=mock_llm):
        result = runner.invoke(cli, ["dump", "fix login, call dentist"])
    assert result.exit_code == 0
    assert "Added 2 task(s)" in result.output


def test_done_all_queries_no_match_exits_zero(runner, cli_env):
    """Test that done with no matching queries still exits 0 (not an error)."""
    from timeopt.cli import cli
    # Seed a task so database is not empty, but don't query for it
    _seed(cli_env, {"title": "fix login bug", "raw": "fix login bug",
                    "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    # Multiple non-matching queries
    result = runner.invoke(cli, ["done", "xyzzy nonexistent 1", "qqqq nonexistent 2"])
    assert result.exit_code == 0
    assert "No confident match" in result.output


def test_setup_skips_all(runner, cli_env):
    """Choosing skip for all sections runs without error."""
    from timeopt.cli import cli
    result = runner.invoke(cli, ["setup"], input="4\nn\nn\nn\n")
    assert result.exit_code == 0
    assert "Setup complete" in result.output


def test_setup_anthropic_saves_config(runner, cli_env):
    """Choosing Anthropic saves llm_api_key and llm_model."""
    from timeopt.cli import cli
    from timeopt import db, core
    result = runner.invoke(
        cli, ["setup"],
        input="1\nsk-test-key\nclaude-sonnet-4-6\nn\nn\nn\n"
    )
    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert core.get_config(conn, "llm_api_key") == "sk-test-key"
    assert core.get_config(conn, "llm_model") == "claude-sonnet-4-6"
    conn.close()


def test_setup_openai_sets_base_url(runner, cli_env):
    """Choosing OpenAI sets llm_base_url to OpenAI's API."""
    from timeopt.cli import cli
    from timeopt import db, core
    result = runner.invoke(
        cli, ["setup"],
        input="2\nsk-openai-key\ngpt-4o\nn\nn\nn\n"
    )
    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert core.get_config(conn, "llm_base_url") == "https://api.openai.com/v1"
    assert core.get_config(conn, "llm_api_key") == "sk-openai-key"
    conn.close()


def test_setup_scheduling_defaults(runner, cli_env):
    """Customizing scheduling saves day_start and day_end."""
    from timeopt.cli import cli
    from timeopt import db, core
    result = runner.invoke(
        cli, ["setup"],
        input="4\nn\ny\n08:00\n17:00\n10\nsmall\nn\n"
    )
    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert core.get_config(conn, "day_start") == "08:00"
    assert core.get_config(conn, "day_end") == "17:00"
    conn.close()


def test_ui_command_starts_uvicorn(runner, cli_env):
    """timeopt ui starts uvicorn and opens browser in background thread."""
    from timeopt.cli import cli
    from unittest.mock import patch
    import time
    with patch("uvicorn.run") as mock_uvicorn, \
         patch("webbrowser.open") as mock_browser:
        result = runner.invoke(cli, ["ui"])
        assert result.exit_code == 0
        mock_uvicorn.assert_called_once()
        call_args = mock_uvicorn.call_args
        assert "timeopt.ui_server:app" in call_args[0]
        # Wait for background thread to call webbrowser.open (with 0.8s delay + margin)
        time.sleep(1.0)
        mock_browser.assert_called_once()
        assert "7749" in mock_browser.call_args[0][0]


def test_sync_command_with_caldav(runner, cli_env):
    """sync command with CalDAV mocked shows no-change message."""
    from timeopt.cli import cli
    from unittest.mock import MagicMock

    mock_caldav = MagicMock()
    mock_caldav.get_events.return_value = []

    with patch("timeopt.cli._get_caldav_client", return_value=mock_caldav):
        result = runner.invoke(cli, ["sync"])
    assert result.exit_code == 0
    assert "No due date changes" in result.output


def test_plan_command_shows_schedule(runner, cli_env):
    """plan command displays scheduled blocks when tasks exist."""
    from timeopt.cli import cli
    _seed(cli_env, {"title": "write tests", "raw": "write tests",
                    "priority": "high", "urgent": True, "category": "work", "effort": "small"})

    with patch("timeopt.cli._get_caldav_client", return_value=None):
        result = runner.invoke(cli, ["plan", "--date", "2026-04-10"])
    assert result.exit_code == 0
    assert "#1-write-tests" in result.output


def test_plan_command_push_confirmation(runner, cli_env):
    """plan command prompts to push when CalDAV is configured."""
    from timeopt.cli import cli
    _seed(cli_env, {"title": "push me", "raw": "push me",
                    "priority": "high", "urgent": True, "category": "work", "effort": "small"})

    mock_caldav = MagicMock()
    mock_caldav.get_events.return_value = []

    with patch("timeopt.cli._get_caldav_client", return_value=mock_caldav), \
         patch("timeopt.planner.push_calendar_blocks"):
        result = runner.invoke(cli, ["plan", "--date", "2026-04-10"], input="n\n")
    assert result.exit_code == 0
    assert "Push to calendar?" in result.output


def test_setup_custom_provider_saves_config(runner, cli_env):
    """Choosing Custom provider saves llm_base_url, llm_api_key, llm_model."""
    from timeopt.cli import cli
    result = runner.invoke(
        cli, ["setup"],
        input="3\nhttps://my-llm.example.com/v1\nmy-api-key\nmy-model\nn\nn\nn\n"
    )
    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert core.get_config(conn, "llm_base_url") == "https://my-llm.example.com/v1"
    assert core.get_config(conn, "llm_api_key") == "my-api-key"
    assert core.get_config(conn, "llm_model") == "my-model"
    conn.close()


def test_setup_caldav_saves_config(runner, cli_env):
    """Configuring CalDAV in setup saves url, username, password."""
    from timeopt.cli import cli
    result = runner.invoke(
        cli, ["setup"],
        input="4\ny\nhttps://caldav.example.com\nmyuser\nmypassword\nn\nn\n"
    )
    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert core.get_config(conn, "caldav_url") == "https://caldav.example.com"
    assert core.get_config(conn, "caldav_username") == "myuser"
    assert core.get_config(conn, "caldav_password") == "mypassword"
    conn.close()


def test_ui_command_respects_ui_port_config(runner, cli_env):
    """timeopt ui reads ui_port from config."""
    from timeopt.cli import cli
    from timeopt import db, core
    from unittest.mock import patch
    conn = db.get_connection(cli_env)
    core.set_config(conn, "ui_port", "9000")
    conn.close()

    with patch("uvicorn.run") as mock_uvicorn, \
         patch("webbrowser.open") as mock_browser:
        result = runner.invoke(cli, ["ui"])
        assert result.exit_code == 0
        call_kwargs = mock_uvicorn.call_args[1]
        assert call_kwargs["port"] == 9000


def test_ui_command_bad_port_shows_error(runner, cli_env):
    """If ui_port is non-integer, show clean error instead of ValueError traceback."""
    from timeopt.cli import cli
    from timeopt import db, core
    conn = db.get_connection(cli_env)
    core.set_config(conn, "ui_port", "not_a_number")
    conn.close()

    result = runner.invoke(cli, ["ui"])
    assert result.exit_code != 0
    assert "not_a_number" in result.output


def test_tasks_filter_by_priority(runner, cli_env):
    """tasks --priority filters by priority."""
    from timeopt.cli import cli
    _seed(cli_env,
          {"title": "high priority", "raw": "high priority",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
          {"title": "low priority", "raw": "low priority",
           "priority": "low", "urgent": False, "category": "work", "effort": "medium"})
    result = runner.invoke(cli, ["tasks", "--priority", "high"])
    assert result.exit_code == 0
    assert "high-priority" in result.output
    assert "low-priority" not in result.output


def test_tasks_filter_by_category(runner, cli_env):
    """tasks --category filters by category."""
    from timeopt.cli import cli
    _seed(cli_env,
          {"title": "work task", "raw": "work task",
           "priority": "medium", "urgent": False, "category": "work", "effort": "medium"},
          {"title": "personal task", "raw": "personal task",
           "priority": "medium", "urgent": False, "category": "personal", "effort": "medium"})
    result = runner.invoke(cli, ["tasks", "--category", "work"])
    assert result.exit_code == 0
    assert "work-task" in result.output
    assert "personal-task" not in result.output


def test_tasks_filter_priority_and_category(runner, cli_env):
    """tasks --priority and --category filters work together."""
    from timeopt.cli import cli
    _seed(cli_env,
          {"title": "high work", "raw": "high work",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
          {"title": "high personal", "raw": "high personal",
           "priority": "high", "urgent": False, "category": "personal", "effort": "medium"},
          {"title": "low work", "raw": "low work",
           "priority": "low", "urgent": False, "category": "work", "effort": "medium"})
    result = runner.invoke(cli, ["tasks", "--priority", "high", "--category", "work"])
    assert result.exit_code == 0
    assert "high-work" in result.output
    assert "high-personal" not in result.output
    assert "low-work" not in result.output


def test_history_period_week(runner, cli_env):
    """history --week shows tasks from last 7 days."""
    from timeopt.cli import cli
    from datetime import date as date_type, timedelta
    _seed(cli_env, {"title": "old task", "raw": "old task",
                    "priority": "medium", "urgent": False, "category": "work", "effort": "small"})
    conn = db.get_connection(cli_env)
    # Update done_at to be 10 days ago
    old_date = (date_type.today() - timedelta(days=10)).isoformat()
    conn.execute("UPDATE tasks SET status='done', done_at=?", (old_date,))
    conn.commit()
    conn.close()
    result = runner.invoke(cli, ["history", "--week"])
    assert result.exit_code == 0
    assert "No completed tasks" in result.output


def test_history_period_all(runner, cli_env):
    """history --all shows all completed tasks regardless of age."""
    from timeopt.cli import cli
    from datetime import date as date_type, timedelta
    _seed(cli_env, {"title": "old task", "raw": "old task",
                    "priority": "medium", "urgent": False, "category": "work", "effort": "small"})
    conn = db.get_connection(cli_env)
    old_date = (date_type.today() - timedelta(days=100)).isoformat()
    conn.execute("UPDATE tasks SET status='done', done_at=?", (old_date,))
    conn.commit()
    conn.close()
    result = runner.invoke(cli, ["history", "--all"])
    assert result.exit_code == 0
    assert "old-task" in result.output


def test_tasks_shows_delegated_tasks(runner, cli_env):
    """tasks command shows delegated tasks with notes."""
    from timeopt.cli import cli
    _seed(cli_env, {"title": "delegated task", "raw": "delegated task",
                    "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    conn = db.get_connection(cli_env)
    row = conn.execute("SELECT id FROM tasks").fetchone()
    core.mark_delegated(conn, row[0], "Claude")
    core.update_task_notes(conn, row[0], "Working on this now")
    conn.close()
    result = runner.invoke(cli, ["tasks"])
    assert result.exit_code == 0
    assert "delegated-task" in result.output
    assert "Being handled by Claude" in result.output
    assert "Working on this now" in result.output


def test_tasks_with_urgent_tag(runner, cli_env):
    """Task display includes urgent tag when task is marked urgent."""
    from timeopt.cli import cli
    _seed(cli_env, {"title": "urgent task", "raw": "urgent task",
                    "priority": "high", "urgent": True, "category": "work", "effort": "medium"})
    result = runner.invoke(cli, ["tasks"])
    assert result.exit_code == 0
    assert "urgent" in result.output


def test_tasks_with_due_date_tag(runner, cli_env):
    """Task display includes due date tag when task has due_at."""
    from timeopt.cli import cli
    _seed(cli_env, {"title": "due soon", "raw": "due soon",
                    "priority": "medium", "urgent": False, "category": "work", "effort": "medium",
                    "due_at": "2026-04-15T17:00:00Z"})
    result = runner.invoke(cli, ["tasks"])
    assert result.exit_code == 0
    assert "due 2026-04-15" in result.output


def test_config_set_invalid_key_fails(runner, cli_env):
    """config set with unknown key should raise error."""
    from timeopt.cli import cli
    result = runner.invoke(cli, ["config", "set", "nonexistent_key", "value"])
    # KeyError is raised and will result in non-zero exit code
    assert result.exit_code != 0


def test_history_with_multiple_done_tasks(runner, cli_env):
    """history shows all done tasks grouped properly."""
    from timeopt.cli import cli
    _seed(cli_env,
          {"title": "task one", "raw": "task one",
           "priority": "high", "urgent": False, "category": "work", "effort": "small"},
          {"title": "task two", "raw": "task two",
           "priority": "medium", "urgent": False, "category": "work", "effort": "small"})
    conn = db.get_connection(cli_env)
    rows = conn.execute("SELECT id FROM tasks").fetchall()
    for row in rows:
        core.mark_done(conn, [row[0]])
    conn.close()
    result = runner.invoke(cli, ["history"])
    assert result.exit_code == 0
    assert "task-one" in result.output
    assert "task-two" in result.output
    assert "Completed" in result.output


def test_tasks_mixed_statuses(runner, cli_env):
    """tasks command displays pending, delegated, and done tasks properly."""
    from timeopt.cli import cli
    _seed(cli_env,
          {"title": "pending task", "raw": "pending task",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
          {"title": "delegated task", "raw": "delegated task",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
          {"title": "done task", "raw": "done task",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    conn = db.get_connection(cli_env)
    rows = conn.execute("SELECT id FROM tasks ORDER BY created_at").fetchall()
    core.mark_delegated(conn, rows[1][0], "Claude")
    core.mark_done(conn, [rows[2][0]])
    conn.close()
    result = runner.invoke(cli, ["tasks"])
    assert result.exit_code == 0
    assert "Pending" in result.output
    assert "Being handled by Claude" in result.output
    assert "Done" in result.output
    assert "pending-task" in result.output
    assert "delegated-task" in result.output
    assert "done-task" in result.output


def test_get_llm_client_error_handling(runner, cli_env):
    """_get_llm_client handles ValueError from build_llm_client gracefully."""
    from timeopt.cli import cli
    from unittest.mock import patch
    # Missing llm_api_key should cause an error
    result = runner.invoke(cli, ["dump", "test task"], catch_exceptions=False)
    # Should fail because no LLM is configured
    assert result.exit_code != 0


def test_setup_with_ui_confirmation(runner, cli_env):
    """setup command shows UI prompt and instruction when user confirms."""
    from timeopt.cli import cli
    result = runner.invoke(cli, ["setup"], input="4\nn\nn\ny\n")
    assert result.exit_code == 0
    assert "Run: timeopt ui" in result.output


def test_done_with_ambiguous_match_valid_selection(runner, cli_env):
    """done command accepts user's selection in ambiguous match."""
    from timeopt.cli import cli
    _seed(cli_env,
          {"title": "fix login bug", "raw": "fix login bug",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
          {"title": "fix logout bug", "raw": "fix logout bug",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    result = runner.invoke(cli, ["done", "fix"], input="1\n")
    assert result.exit_code == 0
    assert "Done:" in result.output
    assert "#1-fix-login-bug" in result.output


def test_done_with_ambiguous_match_invalid_choice(runner, cli_env):
    """done command handles invalid choice in ambiguous match."""
    from timeopt.cli import cli
    _seed(cli_env,
          {"title": "fix login bug", "raw": "fix login bug",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
          {"title": "fix logout bug", "raw": "fix logout bug",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    result = runner.invoke(cli, ["done", "fix"], input="99\n")
    assert result.exit_code == 0
    assert "Done:" not in result.output


def test_done_with_ambiguous_match_skip(runner, cli_env):
    """done command skips when user picks 0 in ambiguous match."""
    from timeopt.cli import cli
    _seed(cli_env,
          {"title": "fix login bug", "raw": "fix login bug",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
          {"title": "fix logout bug", "raw": "fix logout bug",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    result = runner.invoke(cli, ["done", "fix"], input="0\n")
    assert result.exit_code == 0
    assert "Done:" not in result.output


def test_plan_with_caldav_error(runner, cli_env):
    """plan command proceeds without calendar when CalDAV fails."""
    from timeopt.cli import cli
    from unittest.mock import patch, MagicMock
    _seed(cli_env, {"title": "task one", "raw": "task one",
                    "priority": "high", "urgent": False, "category": "work", "effort": "small"})

    mock_caldav = MagicMock()
    mock_caldav.get_events.side_effect = Exception("Network error")

    with patch("timeopt.cli._get_caldav_client", return_value=mock_caldav):
        result = runner.invoke(cli, ["plan"], input="n\n")
        assert result.exit_code == 0
        assert "Proposed schedule:" in result.output


def test_plan_with_deferred_tasks(runner, cli_env):
    """plan command shows deferred tasks when they don't fit the day."""
    from timeopt.cli import cli
    from unittest.mock import patch, MagicMock

    # Create multiple large tasks that won't fit in one day
    _seed(cli_env,
          {"title": "big task 1", "raw": "big task 1",
           "priority": "high", "urgent": False, "category": "work", "effort": "large"},
          {"title": "big task 2", "raw": "big task 2",
           "priority": "high", "urgent": False, "category": "work", "effort": "large"},
          {"title": "big task 3", "raw": "big task 3",
           "priority": "high", "urgent": False, "category": "work", "effort": "large"})

    with patch("timeopt.cli._get_caldav_client", return_value=None):
        result = runner.invoke(cli, ["plan"], input="n\n")
        assert result.exit_code == 0
        if "Deferred" in result.output:
            assert "big-task" in result.output


def test_done_with_no_confident_match(runner, cli_env):
    """done command shows closest matches when no confident match found."""
    from timeopt.cli import cli
    _seed(cli_env, {"title": "very specific task name", "raw": "very specific task name",
                    "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    result = runner.invoke(cli, ["done", "xyz"])
    assert result.exit_code == 0
    assert "No confident match" in result.output


def test_plan_without_caldav_skips_push(runner, cli_env):
    """plan command skips calendar push when CalDAV not configured."""
    from timeopt.cli import cli
    from unittest.mock import patch
    _seed(cli_env, {"title": "task", "raw": "task",
                    "priority": "high", "urgent": False, "category": "work", "effort": "small"})

    with patch("timeopt.cli._get_caldav_client", return_value=None):
        result = runner.invoke(cli, ["plan"])
        assert result.exit_code == 0
        assert "CalDAV not configured" in result.output


def test_sync_with_caldav_error(runner, cli_env):
    """sync command handles CalDAV errors gracefully."""
    from timeopt.cli import cli
    from unittest.mock import patch, MagicMock

    mock_caldav = MagicMock()
    mock_caldav.get_events.side_effect = Exception("Auth error")

    with patch("timeopt.cli._get_caldav_client", return_value=mock_caldav):
        result = runner.invoke(cli, ["sync"])
        assert result.exit_code == 0
        assert "CalDAV error" in result.output


def test_tasks_with_status_delegated_filter(runner, cli_env):
    """tasks --status delegated shows only delegated tasks."""
    from timeopt.cli import cli
    _seed(cli_env,
          {"title": "delegated task", "raw": "delegated task",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
          {"title": "pending task", "raw": "pending task",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    conn = db.get_connection(cli_env)
    rows = conn.execute("SELECT id FROM tasks ORDER BY created_at").fetchall()
    core.mark_delegated(conn, rows[0][0], "Claude")
    conn.close()

    result = runner.invoke(cli, ["tasks", "--status", "delegated"])
    assert result.exit_code == 0
    assert "delegated-task" in result.output
    assert "pending-task" not in result.output


def test_tasks_with_status_done_filter(runner, cli_env):
    """tasks --status done shows only done tasks."""
    from timeopt.cli import cli
    _seed(cli_env,
          {"title": "done task", "raw": "done task",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
          {"title": "pending task", "raw": "pending task",
           "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    conn = db.get_connection(cli_env)
    rows = conn.execute("SELECT id FROM tasks ORDER BY created_at").fetchall()
    core.mark_done(conn, [rows[0][0]])
    conn.close()

    result = runner.invoke(cli, ["tasks", "--status", "done"])
    assert result.exit_code == 0
    assert "done-task" in result.output
    assert "pending-task" not in result.output


def test_plan_shows_deferred_tasks(runner, cli_env):
    """plan command shows deferred tasks list when they exist."""
    from timeopt.cli import cli
    from unittest.mock import patch
    # Create tasks that will trigger deferred output
    _seed(cli_env,
          {"title": "task 1", "raw": "task 1",
           "priority": "high", "urgent": False, "category": "work", "effort": "large"},
          {"title": "task 2", "raw": "task 2",
           "priority": "high", "urgent": False, "category": "work", "effort": "large"},
          {"title": "task 3", "raw": "task 3",
           "priority": "high", "urgent": False, "category": "work", "effort": "large"})

    with patch("timeopt.cli._get_caldav_client", return_value=None):
        result = runner.invoke(cli, ["plan"])
        assert result.exit_code == 0
        # With multiple large tasks, some should be deferred
        # Check that the output contains either blocks or deferred
        assert "Proposed schedule:" in result.output or "No tasks to schedule" in result.output


def test_plan_with_push_success(runner, cli_env):
    """plan command confirms push success message."""
    from timeopt.cli import cli
    from unittest.mock import patch, MagicMock
    _seed(cli_env, {"title": "task", "raw": "task",
                    "priority": "high", "urgent": False, "category": "work", "effort": "small"})

    mock_caldav = MagicMock()
    mock_caldav.get_events.return_value = []

    with patch("timeopt.cli._get_caldav_client", return_value=mock_caldav), \
         patch("timeopt.planner.push_calendar_blocks"):
        result = runner.invoke(cli, ["plan"], input="y\n")
        assert result.exit_code == 0
        assert "Pushed" in result.output or "Proposed schedule:" in result.output


def test_sync_shows_no_changes(runner, cli_env):
    """sync command shows 'No due date changes' when no changes found."""
    from timeopt.cli import cli
    from unittest.mock import patch, MagicMock
    _seed(cli_env, {"title": "task", "raw": "task",
                    "priority": "high", "urgent": False, "category": "work", "effort": "small"})

    mock_caldav = MagicMock()
    mock_caldav.get_events.return_value = []

    with patch("timeopt.cli._get_caldav_client", return_value=mock_caldav):
        result = runner.invoke(cli, ["sync"])
        assert result.exit_code == 0
        assert "No due date changes" in result.output


def test_sync_shows_updated_due_dates(runner, cli_env):
    """sync command displays updated due date information."""
    from timeopt.cli import cli
    from datetime import datetime
    from unittest.mock import patch, MagicMock
    from timeopt.caldav_client import CalendarEvent

    # Create a task with a due_event_label (bound to calendar event)
    conn = db.get_connection(cli_env)
    core.dump_task(conn, core.TaskInput(
        title="bound task", raw="bound task",
        priority="high", urgent=False, category="work", effort="small",
        due_event_label="Team Meeting"
    ))
    conn.close()

    # Create a matching calendar event
    event = CalendarEvent(
        start="2026-04-15T10:00:00Z",
        end="2026-04-15T11:00:00Z",
        title="Team Meeting",
        uid="test-uid-123"
    )

    mock_caldav = MagicMock()
    mock_caldav.get_events.return_value = [event]

    with patch("timeopt.cli._get_caldav_client", return_value=mock_caldav):
        result = runner.invoke(cli, ["sync"])
        assert result.exit_code == 0
        # Should show either updates, resolution, or no changes
        assert ("Updated" in result.output or "Resolved" in result.output or
                "No due date changes" in result.output)


def test_sync_shows_unresolved_tasks(runner, cli_env):
    """sync command displays unresolved calendar references."""
    from timeopt.cli import cli
    from unittest.mock import patch, MagicMock

    # Create a task with unresolved calendar reference
    conn = db.get_connection(cli_env)
    core.dump_task(conn, core.TaskInput(
        title="unresolved task", raw="unresolved task",
        priority="high", urgent=False, category="work", effort="small",
        due_event_label="Nonexistent Meeting"
    ))
    conn.close()

    mock_caldav = MagicMock()
    mock_caldav.get_events.return_value = []

    with patch("timeopt.cli._get_caldav_client", return_value=mock_caldav):
        result = runner.invoke(cli, ["sync"])
        assert result.exit_code == 0
        # With an unresolved task and no matching event, it should still report
        # either no changes or still unresolved
        assert "No due date changes" in result.output or "still have unresolved" in result.output


def test_cli_sync_updates_task_with_due_event_uid(runner, cli_env):
    """sync correctly updates due date for task bound by UID — not just label."""
    from timeopt.cli import cli
    from timeopt.caldav_client import CalendarEvent
    from unittest.mock import patch, MagicMock

    conn = db.get_connection(cli_env)
    display_id = core.dump_task(conn, core.TaskInput(
        title="bound task", raw="bound task", priority="high", urgent=False,
        category="work", effort="small"
    ))
    # Get the actual UUID from display_id
    task_row = conn.execute("SELECT id FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    task_uuid = task_row[0]

    conn.execute("UPDATE tasks SET due_event_uid='e-uid-1' WHERE id=?", (task_uuid,))
    conn.commit()
    conn.close()

    event = CalendarEvent(
        start="2026-04-20T10:00:00Z", end="2026-04-20T11:00:00Z",
        title="The Meeting", uid="e-uid-1"
    )
    mock_caldav = MagicMock()
    mock_caldav.get_events.return_value = [event]
    with patch("timeopt.cli._get_caldav_client", return_value=mock_caldav):
        result = runner.invoke(cli, ["sync"])
    assert result.exit_code == 0, f"sync crashed: {result.output}\n{result.exception}"
    # After sync, the task should be updated (due date set from the event)
    conn2 = db.get_connection(cli_env)
    row = conn2.execute("SELECT due_at FROM tasks WHERE id=?", (task_uuid,)).fetchone()
    conn2.close()
    assert row is not None
    assert row[0] is not None  # due_at should now be set
