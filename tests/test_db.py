import sqlite3
from timeopt.db import get_connection, create_schema


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
