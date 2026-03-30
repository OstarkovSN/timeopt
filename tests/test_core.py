from timeopt.core import get_config, set_config, get_all_config

DEFAULTS = {
    "day_start": "09:00",
    "day_end": "18:00",
    "break_duration_min": "15",
    "default_effort": "medium",
    "effort_small_min": "30",
    "effort_medium_min": "60",
    "effort_large_min": "120",
    "hide_done_after_days": "7",
    "fuzzy_match_min_score": "80",
    "fuzzy_match_ask_gap": "10",
    "delegation_max_tool_calls": "10",
}


def test_get_config_returns_default(conn):
    assert get_config(conn, "day_start") == "09:00"


def test_get_config_returns_override(conn):
    set_config(conn, "day_start", "08:00")
    assert get_config(conn, "day_start") == "08:00"


def test_get_config_unknown_key_raises(conn):
    import pytest
    with pytest.raises(KeyError):
        get_config(conn, "nonexistent_key")


def test_get_all_config_returns_merged(conn):
    set_config(conn, "day_start", "08:00")
    cfg = get_all_config(conn)
    assert cfg["day_start"] == "08:00"
    assert cfg["day_end"] == "18:00"  # default still present


def test_set_config_persists(conn):
    set_config(conn, "default_effort", "large")
    assert get_config(conn, "default_effort") == "large"


from timeopt.core import create_task, TaskInput


def test_create_task_returns_display_id(conn):
    task = TaskInput(title="fix login bug", raw="fix login bug",
                     priority="high", urgent=False, category="work", effort="medium")
    display_id = create_task(conn, task)
    assert display_id == "#1-fix-login-bug"


def test_create_task_stores_in_db(conn):
    task = TaskInput(title="call dentist", raw="call dentist",
                     priority="medium", urgent=False, category="personal", effort="small")
    display_id = create_task(conn, task)
    row = conn.execute(
        "SELECT * FROM tasks WHERE display_id = ?", (display_id,)
    ).fetchone()
    assert row is not None
    assert row["title"] == "call dentist"
    assert row["status"] == "pending"


def test_create_task_slug_strips_special_chars(conn):
    task = TaskInput(title="Fix login bug!", raw="Fix login bug!",
                     priority="high", urgent=False, category="work", effort="medium")
    display_id = create_task(conn, task)
    assert display_id == "#1-fix-login-bug"


def test_create_two_tasks_get_sequential_ids(conn):
    t1 = TaskInput(title="task one", raw="task one",
                   priority="low", urgent=False, category="other", effort="small")
    t2 = TaskInput(title="task two", raw="task two",
                   priority="low", urgent=False, category="other", effort="small")
    id1 = create_task(conn, t1)
    id2 = create_task(conn, t2)
    assert id1 == "#1-task-one"
    assert id2 == "#2-task-two"


def test_create_task_recycles_id_after_done(conn):
    t1 = TaskInput(title="task one", raw="task one",
                   priority="low", urgent=False, category="other", effort="small")
    display_id = create_task(conn, t1)
    conn.execute("UPDATE tasks SET status='done' WHERE display_id=?", (display_id,))
    conn.commit()

    t2 = TaskInput(title="task two", raw="task two",
                   priority="low", urgent=False, category="other", effort="small")
    id2 = create_task(conn, t2)
    assert id2 == "#1-task-two"  # recycled #1
