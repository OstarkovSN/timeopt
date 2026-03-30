import sqlite3
from pathlib import Path


def get_connection(path: str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection. Use ':memory:' for tests."""
    if path is None:
        path = str(Path.home() / ".timeopt" / "timeopt.db")
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            short_id INTEGER NOT NULL,
            display_id TEXT NOT NULL,
            title TEXT NOT NULL,
            raw TEXT NOT NULL,
            priority TEXT NOT NULL CHECK(priority IN ('high', 'medium', 'low')),
            urgent INTEGER NOT NULL DEFAULT 0,
            category TEXT NOT NULL CHECK(category IN ('work', 'personal', 'errands', 'other')),
            effort TEXT CHECK(effort IN ('small', 'medium', 'large')),
            due_at TEXT,
            due_event_uid TEXT,
            due_event_label TEXT,
            due_event_offset_min INTEGER,
            due_unresolved INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'delegated', 'done')),
            done_at TEXT,
            notes TEXT
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_short_id_active
            ON tasks(short_id) WHERE status IN ('pending', 'delegated');

        CREATE TABLE IF NOT EXISTS calendar_blocks (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(id),
            caldav_uid TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            duration_min INTEGER NOT NULL,
            plan_date TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    conn.commit()


def next_short_id(conn: sqlite3.Connection) -> int:
    """
    Find the lowest free short_id.
    Tries 1–99 first (recycling pool). Falls back to MAX+1 if all taken.
    'Free' means not held by any pending or delegated task.
    """
    occupied = {
        row[0]
        for row in conn.execute(
            "SELECT short_id FROM tasks WHERE status IN ('pending', 'delegated')"
        ).fetchall()
    }
    for i in range(1, 100):
        if i not in occupied:
            return i
    max_id = conn.execute("SELECT MAX(short_id) FROM tasks").fetchone()[0] or 0
    return max(max_id + 1, 100)
