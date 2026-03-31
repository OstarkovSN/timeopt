import os
import pytest
from unittest.mock import patch
from timeopt import db, core


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
