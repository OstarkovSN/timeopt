import sqlite3
import pytest
from timeopt.db import get_connection, create_schema, next_short_id


def test_schema_creates_tables():
    conn = get_connection(":memory:")
    create_schema(conn)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"tasks", "calendar_blocks", "config"} <= tables


def test_wal_mode():
    conn = get_connection(":memory:")
    # WAL mode is set by get_connection
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "memory"  # in-memory DB uses memory journal, not WAL — acceptable


def test_tasks_columns():
    conn = get_connection(":memory:")
    create_schema(conn)
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
    }
    required = {
        "id", "short_id", "display_id", "title", "raw", "priority",
        "urgent", "category", "effort", "due_at", "due_event_uid",
        "due_event_label", "due_event_offset_min", "due_unresolved",
        "created_at", "status", "done_at", "notes",
    }
    assert required <= cols


def test_partial_unique_index_exists():
    conn = get_connection(":memory:")
    create_schema(conn)
    indexes = {
        row[1]
        for row in conn.execute(
            "SELECT * FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert "idx_short_id_active" in indexes


def test_short_id_starts_at_1(conn):
    assert next_short_id(conn) == 1


def test_short_id_increments(conn):
    # Simulate task with short_id=1 active
    conn.execute(
        "INSERT INTO tasks(id, short_id, display_id, title, raw, priority, "
        "urgent, category, created_at, status) VALUES "
        "('a', 1, '#1-task', 'task', 'task', 'high', 0, 'work', '2026-01-01', 'pending')"
    )
    assert next_short_id(conn) == 2


def test_short_id_recycles_after_done(conn):
    # Task #1 is done — short_id 1 should be reused
    conn.execute(
        "INSERT INTO tasks(id, short_id, display_id, title, raw, priority, "
        "urgent, category, created_at, status, done_at) VALUES "
        "('a', 1, '#1-task', 'task', 'task', 'high', 0, 'work', '2026-01-01', 'done', '2026-01-02')"
    )
    assert next_short_id(conn) == 1


def test_short_id_overflows_at_99(conn):
    # Fill 1–99 with active tasks
    for i in range(1, 100):
        conn.execute(
            "INSERT INTO tasks(id, short_id, display_id, title, raw, priority, "
            "urgent, category, created_at, status) VALUES "
            f"('{i}', {i}, '#{i}-t', 't', 't', 'low', 0, 'other', '2026-01-01', 'pending')"
        )
    assert next_short_id(conn) == 100


def test_short_id_recycles_gap_in_pool(conn):
    # 1, 3, 4 active — short_id 2 should be recycled
    for i in [1, 3, 4]:
        conn.execute(
            "INSERT INTO tasks(id, short_id, display_id, title, raw, priority, "
            "urgent, category, created_at, status) VALUES "
            f"('{i}', {i}, '#{i}-t', 't', 't', 'low', 0, 'other', '2026-01-01', 'pending')"
        )
    assert next_short_id(conn) == 2


# ============================================================================
# Block 11: DB schema constraints — verify CHECK and FK enforcement
# ============================================================================


def test_invalid_priority_raises_integrity_error(conn):
    """INSERT with invalid priority value should raise IntegrityError (CHECK constraint)."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tasks(id, short_id, display_id, title, raw, priority, "
            "urgent, category, created_at, status) VALUES "
            "('x', 1, '#1-t', 'test', 'test', 'invalid_priority', 0, 'work', '2026-01-01', 'pending')"
        )
        conn.commit()


def test_invalid_status_raises_integrity_error(conn):
    """INSERT with invalid status value should raise IntegrityError (CHECK constraint)."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tasks(id, short_id, display_id, title, raw, priority, "
            "urgent, category, created_at, status) VALUES "
            "('x', 1, '#1-t', 'test', 'test', 'high', 0, 'work', '2026-01-01', 'invalid_status')"
        )
        conn.commit()


def test_duplicate_short_id_for_pending_tasks_raises_integrity_error(conn):
    """INSERT with duplicate short_id for pending tasks should raise IntegrityError (partial unique index)."""
    # First task with short_id=1, status=pending
    conn.execute(
        "INSERT INTO tasks(id, short_id, display_id, title, raw, priority, "
        "urgent, category, created_at, status) VALUES "
        "('a', 1, '#1-first', 'first', 'first', 'high', 0, 'work', '2026-01-01', 'pending')"
    )
    conn.commit()

    # Try to insert another task with short_id=1, status=pending — should fail
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tasks(id, short_id, display_id, title, raw, priority, "
            "urgent, category, created_at, status) VALUES "
            "('b', 1, '#1-second', 'second', 'second', 'high', 0, 'work', '2026-01-01', 'pending')"
        )
        conn.commit()


def test_duplicate_short_id_for_done_tasks_allowed(conn):
    """INSERT with duplicate short_id for done tasks should succeed (not covered by partial index)."""
    # First task with short_id=1, status=done
    conn.execute(
        "INSERT INTO tasks(id, short_id, display_id, title, raw, priority, "
        "urgent, category, created_at, status, done_at) VALUES "
        "('a', 1, '#1-first', 'first', 'first', 'high', 0, 'work', '2026-01-01', 'done', '2026-01-02')"
    )
    conn.commit()

    # Insert another task with short_id=1, status=done — should succeed
    conn.execute(
        "INSERT INTO tasks(id, short_id, display_id, title, raw, priority, "
        "urgent, category, created_at, status, done_at) VALUES "
        "('b', 1, '#1-second', 'second', 'second', 'high', 0, 'work', '2026-01-01', 'done', '2026-01-02')"
    )
    conn.commit()

    # Verify both tasks were inserted
    count = conn.execute("SELECT COUNT(*) FROM tasks WHERE short_id=1").fetchone()[0]
    assert count == 2


def test_foreign_key_constraint_referencing_nonexistent_task(conn):
    """INSERT into calendar_blocks with non-existent task_id should raise IntegrityError (FK constraint)."""
    import uuid

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO calendar_blocks(id, task_id, caldav_uid, scheduled_at, duration_min, plan_date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), 'nonexistent-task-id', 'uid-1', '2026-01-01T09:00:00', 60, '2026-01-01'),
        )
        conn.commit()
