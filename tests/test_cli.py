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
    """timeopt ui starts uvicorn and opens browser."""
    from timeopt.cli import cli
    from unittest.mock import patch
    with patch("uvicorn.run") as mock_uvicorn, \
         patch("webbrowser.open") as mock_browser:
        result = runner.invoke(cli, ["ui"])
        assert result.exit_code == 0
        mock_uvicorn.assert_called_once()
        call_args = mock_uvicorn.call_args
        assert "timeopt.ui_server:app" in call_args[0]
        mock_browser.assert_called_once()
        assert "7749" in mock_browser.call_args[0][0]


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
        assert "9000" in mock_browser.call_args[0][0]
