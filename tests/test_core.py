from timeopt.core import get_config, set_config, get_all_config
from datetime import datetime, timezone, timedelta

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


from timeopt.core import mark_done, mark_delegated, update_task_notes, return_to_pending


def _make_task(conn, title="fix bug", priority="high", urgent=False,
               category="work", effort="medium") -> str:
    task = TaskInput(title=title, raw=title, priority=priority,
                     urgent=urgent, category=category, effort=effort)
    return create_task(conn, task)


def test_mark_done_sets_status(conn):
    display_id = _make_task(conn)
    row = conn.execute("SELECT id FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    mark_done(conn, [row["id"]])
    row = conn.execute("SELECT status, done_at FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    assert row["status"] == "done"
    assert row["done_at"] is not None


def test_mark_done_rejects_already_done(conn):
    import pytest
    display_id = _make_task(conn)
    row = conn.execute("SELECT id FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    mark_done(conn, [row["id"]])
    with pytest.raises(ValueError, match="not active"):
        mark_done(conn, [row["id"]])


def test_mark_delegated_sets_status(conn):
    display_id = _make_task(conn)
    row = conn.execute("SELECT id FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    mark_delegated(conn, row["id"], notes="starting delegation")
    row = conn.execute("SELECT status, notes FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    assert row["status"] == "delegated"
    assert "starting delegation" in row["notes"]


def test_update_task_notes_appends(conn):
    display_id = _make_task(conn)
    row = conn.execute("SELECT id FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    mark_delegated(conn, row["id"])
    update_task_notes(conn, row["id"], "first note")
    update_task_notes(conn, row["id"], "second note")
    notes = conn.execute("SELECT notes FROM tasks WHERE id=?", (row["id"],)).fetchone()[0]
    assert "first note" in notes
    assert "second note" in notes


def test_update_task_notes_rejects_non_delegated(conn):
    import pytest
    display_id = _make_task(conn)
    row = conn.execute("SELECT id FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    with pytest.raises(ValueError, match="not delegated"):
        update_task_notes(conn, row["id"], "note")


def test_return_to_pending(conn):
    display_id = _make_task(conn)
    row = conn.execute("SELECT id FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    mark_delegated(conn, row["id"])
    return_to_pending(conn, row["id"], "no tools available")
    row = conn.execute("SELECT status, notes FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    assert row["status"] == "pending"
    assert "no tools available" in row["notes"]


from timeopt.core import list_tasks


def test_list_tasks_returns_pending_by_default(conn):
    _make_task(conn, title="task a")
    _make_task(conn, title="task b")
    tasks = list_tasks(conn)
    assert len(tasks) == 2
    assert all(t["status"] == "pending" for t in tasks)


def test_list_tasks_excludes_old_done(conn):
    display_id = _make_task(conn, title="old task")
    row = conn.execute("SELECT id FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    # Set done_at to 10 days ago
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    conn.execute("UPDATE tasks SET status='done', done_at=? WHERE id=?", (old, row["id"]))
    conn.commit()
    tasks = list_tasks(conn)
    assert len(tasks) == 0


def test_list_tasks_includes_recent_done(conn):
    display_id = _make_task(conn, title="recent done")
    row = conn.execute("SELECT id FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE tasks SET status='done', done_at=? WHERE id=?", (now, row["id"]))
    conn.commit()
    tasks = list_tasks(conn, include_old_done=True)
    assert any(t["display_id"] == display_id for t in tasks)


def test_list_tasks_returns_display_fields_only(conn):
    _make_task(conn)
    tasks = list_tasks(conn)
    assert len(tasks) == 1
    t = tasks[0]
    assert "display_id" in t
    assert "title" in t
    assert "priority" in t
    # raw and created_at should NOT be in default response
    assert "raw" not in t
    assert "created_at" not in t


def test_list_tasks_includes_delegated(conn):
    display_id = _make_task(conn, title="delegate me")
    row = conn.execute("SELECT id FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    mark_delegated(conn, row["id"])
    tasks = list_tasks(conn)
    assert any(t["display_id"] == display_id for t in tasks)


from timeopt.core import get_task, fuzzy_match_tasks


def test_get_task_returns_full_row(conn):
    display_id = _make_task(conn, title="full detail task")
    row = conn.execute("SELECT id FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    task = get_task(conn, row["id"])
    assert "raw" in task
    assert "created_at" in task
    assert task["title"] == "full detail task"


def test_get_task_not_found_raises(conn):
    import pytest
    with pytest.raises(ValueError, match="not found"):
        get_task(conn, "nonexistent-id")


def test_fuzzy_match_finds_clear_winner(conn):
    _make_task(conn, title="fix login bug")
    _make_task(conn, title="call dentist")
    matches = fuzzy_match_tasks(conn, "fix login")
    assert len(matches) > 0
    assert matches[0]["title"] == "fix login bug"
    assert matches[0]["score"] >= 80


def test_fuzzy_match_only_searches_active(conn):
    display_id = _make_task(conn, title="done task")
    row = conn.execute("SELECT id FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    mark_done(conn, [row["id"]])
    matches = fuzzy_match_tasks(conn, "done task")
    assert len(matches) == 0


def test_fuzzy_match_returns_sorted_by_score(conn):
    _make_task(conn, title="fix login bug")
    _make_task(conn, title="fix login redirect")
    matches = fuzzy_match_tasks(conn, "fix login")
    assert len(matches) >= 2
    assert matches[0]["score"] >= matches[1]["score"]
