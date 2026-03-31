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
