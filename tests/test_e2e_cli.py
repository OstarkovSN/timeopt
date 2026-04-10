"""E2E tests for the timeopt CLI — spawn real subprocess via `uv run timeopt`."""
import os
import subprocess
import pytest

from timeopt.db import get_connection, create_schema
from timeopt.core import dump_task, TaskInput


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def e2e(tmp_path):
    db = str(tmp_path / "e2e.db")
    env = {**os.environ, "TIMEOPT_DB": db}

    def run(*args):
        return subprocess.run(
            ["uv", "run", "timeopt", *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=PROJECT_ROOT,
        )

    return run


@pytest.fixture
def seeded_e2e(tmp_path):
    """Fixture that provides a run() helper and a pre-seeded DB with one pending task."""
    db = str(tmp_path / "e2e.db")
    env = {**os.environ, "TIMEOPT_DB": db}

    conn = get_connection(db)
    create_schema(conn)
    task = TaskInput(
        title="fix login bug",
        raw="fix login bug",
        priority="high",
        urgent=False,
        category="work",
        effort="medium",
    )
    display_id = dump_task(conn, task)
    conn.close()

    def run(*args):
        return subprocess.run(
            ["uv", "run", "timeopt", *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=PROJECT_ROOT,
        )

    return run, display_id


@pytest.mark.e2e
def test_cli_starts(e2e):
    """timeopt tasks on empty DB exits 0 and says 'No tasks'."""
    result = e2e("tasks")
    assert result.returncode == 0
    assert "No tasks" in result.stdout


@pytest.mark.e2e
def test_tasks_shows_seeded(seeded_e2e):
    """After seeding via DB, timeopt tasks shows the task's display_id."""
    run, display_id = seeded_e2e
    result = run("tasks")
    assert result.returncode == 0
    assert display_id in result.stdout


@pytest.mark.e2e
def test_done_marks_task(seeded_e2e):
    """timeopt done <query> exits 0 and prints a completion indicator."""
    run, display_id = seeded_e2e
    result = run("done", "fix login")
    assert result.returncode == 0
    assert "✓" in result.stdout or "done" in result.stdout.lower()


@pytest.mark.e2e
def test_config_round_trip(e2e):
    """config set then config get returns the stored value."""
    set_result = e2e("config", "set", "day_start", "08:00")
    assert set_result.returncode == 0

    get_result = e2e("config", "get", "day_start")
    assert get_result.returncode == 0
    assert "08:00" in get_result.stdout


@pytest.mark.e2e
def test_plan_no_caldav(seeded_e2e):
    """timeopt plan --date exits 0 even without CalDAV configured."""
    run, _ = seeded_e2e
    result = run("plan", "--date", "2026-04-01")
    assert result.returncode == 0


@pytest.mark.e2e
def test_plan_invalid_date(e2e):
    """timeopt plan with an invalid date exits non-zero."""
    result = e2e("plan", "--date", "not-a-date")
    assert result.returncode != 0
