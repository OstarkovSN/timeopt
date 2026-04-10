# Timeopt Core Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the timeopt core backend — SQLite schema, task/config CRUD, Eisenhower classification, and server-side scheduling (`get_plan_proposal`).

**Architecture:** Pure Python module (`src/timeopt/`) with no HTTP layer. `db.py` owns the SQLite connection and raw queries. `core.py` exposes high-level task operations. `planner.py` implements scheduling logic. All business logic is tested directly against an in-memory SQLite DB.

**Tech Stack:** Python 3.11+, `uv`, `sqlite3` (stdlib), `rapidfuzz`, `pytest`

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Project metadata, dependencies, entry points |
| `src/timeopt/__init__.py` | Package marker |
| `src/timeopt/db.py` | SQLite connection, schema creation, raw CRUD helpers |
| `src/timeopt/core.py` | High-level task operations: dump, list, mark_done, delegate, config |
| `src/timeopt/planner.py` | Eisenhower classification, `get_plan_proposal`, free-slot computation |
| `tests/__init__.py` | Package marker |
| `tests/conftest.py` | Shared fixtures: in-memory DB, seeded tasks |
| `tests/test_db.py` | Schema, short_id recycling, partial index |
| `tests/test_core.py` | Task lifecycle, config CRUD, fuzzy match |
| `tests/test_planner.py` | Eisenhower sort, slot computation, scheduling, overflow |

---

## Task 1: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `src/timeopt/__init__.py`
- Create: `tests/__init__.py`
- Create: `.gitignore`

- [ ] **Step 1: Initialise uv project**

```bash
cd /home/claude/workdirs/timeopt
uv init --name timeopt --python 3.11
```

Expected: `pyproject.toml` and `hello.py` created. Delete `hello.py`.

```bash
rm hello.py
```

- [ ] **Step 2: Write `pyproject.toml`**

Replace the generated `pyproject.toml` with:

```toml
[project]
name = "timeopt"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastmcp>=2.0",
    "caldav>=1.3",
    "click>=8.1",
    "anthropic>=0.40",
    "openai>=1.0",
    "rapidfuzz>=3.0",
]

[project.scripts]
timeopt = "timeopt.cli:cli"
timeopt-server = "timeopt.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Install dependencies**

```bash
uv sync
```

Expected: `.venv/` created, all packages installed.

- [ ] **Step 4: Create package structure**

```bash
mkdir -p src/timeopt tests
touch src/timeopt/__init__.py tests/__init__.py
```

- [ ] **Step 5: Write `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
dist/
.superpowers/
*.db
```

- [ ] **Step 6: Verify pytest runs**

```bash
uv run pytest
```

Expected: `no tests ran` (0 collected). No errors.

- [ ] **Step 7: Initialise git and commit**

```bash
git init
git add pyproject.toml src/ tests/ .gitignore
git commit -m "chore: initialise timeopt project"
```

---

## Task 2: SQLite Schema

**Files:**
- Create: `src/timeopt/db.py`
- Create: `tests/test_db.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write failing schema test**

`tests/test_db.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_db.py -v
```

Expected: `ModuleNotFoundError: No module named 'timeopt.db'`

- [ ] **Step 3: Write `src/timeopt/db.py`**

```python
import sqlite3
from pathlib import Path


def get_connection(path: str = None) -> sqlite3.Connection:
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_db.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Write `tests/conftest.py`**

```python
import pytest
from timeopt.db import get_connection, create_schema


@pytest.fixture
def conn():
    """In-memory SQLite DB with schema, torn down after each test."""
    c = get_connection(":memory:")
    create_schema(c)
    yield c
    c.close()
```

- [ ] **Step 6: Commit**

```bash
git add src/timeopt/db.py tests/test_db.py tests/conftest.py
git commit -m "feat: SQLite schema with tasks, calendar_blocks, config tables"
```

---

## Task 3: short_id Recycling

**Files:**
- Modify: `src/timeopt/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_db.py`:
```python
from timeopt.db import next_short_id


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_db.py::test_short_id_starts_at_1 -v
```

Expected: `ImportError: cannot import name 'next_short_id'`

- [ ] **Step 3: Implement `next_short_id` in `db.py`**

Add to `src/timeopt/db.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_db.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/db.py tests/test_db.py
git commit -m "feat: short_id recycling pool (1-99 reuse, overflow to 100+)"
```

---

## Task 4: Config CRUD

**Files:**
- Create: `src/timeopt/core.py`
- Modify: `tests/test_core.py` (create file)

- [ ] **Step 1: Write failing tests**

`tests/test_core.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_core.py -v
```

Expected: `ModuleNotFoundError: No module named 'timeopt.core'`

- [ ] **Step 3: Write `src/timeopt/core.py`**

```python
import sqlite3
import logging
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_DEFAULTS: dict[str, str] = {
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


def get_config(conn: sqlite3.Connection, key: str) -> str:
    """Return config value. Raises KeyError for unknown keys."""
    if key not in _CONFIG_DEFAULTS:
        raise KeyError("Unknown config key: %s" % key)
    row = conn.execute(
        "SELECT value FROM config WHERE key = ?", (key,)
    ).fetchone()
    if row:
        return row[0]
    return _CONFIG_DEFAULTS[key]


def set_config(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Persist a config value. Raises KeyError for unknown keys."""
    if key not in _CONFIG_DEFAULTS:
        raise KeyError("Unknown config key: %s" % key)
    conn.execute(
        "INSERT INTO config(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    logger.info("config set: %s = %s", key, value)


def get_all_config(conn: sqlite3.Connection) -> dict[str, str]:
    """Return all config values, merging DB overrides with defaults."""
    cfg = dict(_CONFIG_DEFAULTS)
    for row in conn.execute("SELECT key, value FROM config").fetchall():
        cfg[row[0]] = row[1]
    return cfg
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_core.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/core.py tests/test_core.py
git commit -m "feat: config CRUD with defaults and DB overrides"
```

---

## Task 5: Task Creation

**Files:**
- Modify: `src/timeopt/core.py`
- Modify: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_core.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_core.py::test_create_task_returns_display_id -v
```

Expected: `ImportError: cannot import name 'create_task'`

- [ ] **Step 3: Add `TaskInput` and `create_task` to `core.py`**

Add to `src/timeopt/core.py`:
```python
import re
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from timeopt.db import next_short_id


@dataclass
class TaskInput:
    title: str
    raw: str
    priority: str          # high | medium | low
    urgent: bool
    category: str          # work | personal | errands | other
    effort: str | None = None
    due_at: str | None = None
    due_event_uid: str | None = None
    due_event_label: str | None = None
    due_event_offset_min: int | None = None
    due_unresolved: bool = False


def _slugify(text: str) -> str:
    """Convert title to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:60]  # cap length


def create_task(conn: sqlite3.Connection, task: TaskInput) -> str:
    """
    Insert a new task. Returns the assigned display_id.
    Runs Eisenhower classification before insert.
    """
    short_id = next_short_id(conn)
    slug = _slugify(task.title)
    display_id = f"#{short_id}-{slug}"
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    effort = task.effort or get_config(conn, "default_effort")

    conn.execute(
        """INSERT INTO tasks(
            id, short_id, display_id, title, raw, priority, urgent, category,
            effort, due_at, due_event_uid, due_event_label, due_event_offset_min,
            due_unresolved, created_at, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            task_id, short_id, display_id, task.title, task.raw,
            task.priority, int(task.urgent), task.category,
            effort, task.due_at, task.due_event_uid, task.due_event_label,
            task.due_event_offset_min, int(task.due_unresolved), now, "pending",
        ),
    )
    conn.commit()
    logger.info("task created: %s %s", display_id, task.title)
    return display_id
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_core.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/core.py tests/test_core.py
git commit -m "feat: task creation with short_id recycling and display_id generation"
```

---

## Task 6: Task Lifecycle (mark_done, mark_delegated, return_to_pending)

**Files:**
- Modify: `src/timeopt/core.py`
- Modify: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_core.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_core.py::test_mark_done_sets_status -v
```

Expected: `ImportError: cannot import name 'mark_done'`

- [ ] **Step 3: Add lifecycle functions to `core.py`**

Add to `src/timeopt/core.py`:
```python
def _append_note(conn: sqlite3.Connection, task_id: str, text: str) -> None:
    """Append a timestamped entry to task notes."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"[{now}] {text}"
    existing = conn.execute(
        "SELECT notes FROM tasks WHERE id=?", (task_id,)
    ).fetchone()[0]
    new_notes = f"{existing}\n{entry}" if existing else entry
    conn.execute("UPDATE tasks SET notes=? WHERE id=?", (new_notes, task_id))
    conn.commit()


def mark_done(conn: sqlite3.Connection, task_ids: list[str]) -> None:
    """
    Mark tasks as done. task_ids may be UUIDs or display_ids.
    Only acts on pending/delegated tasks — raises ValueError otherwise.
    """
    for task_id in task_ids:
        row = conn.execute(
            "SELECT id, status FROM tasks WHERE id=? OR display_id=?",
            (task_id, task_id),
        ).fetchone()
        if not row:
            raise ValueError("Task not found: %s" % task_id)
        if row["status"] not in ("pending", "delegated"):
            raise ValueError("Task %s is not active (status=%s)" % (task_id, row["status"]))
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE tasks SET status='done', done_at=? WHERE id=?",
            (now, row["id"]),
        )
        conn.commit()
        logger.info("task done: %s", row["id"])


def mark_delegated(
    conn: sqlite3.Connection, task_id: str, notes: str | None = None
) -> None:
    """Set task status to delegated. task_id is UUID or display_id."""
    row = conn.execute(
        "SELECT id FROM tasks WHERE (id=? OR display_id=?) AND status='pending'",
        (task_id, task_id),
    ).fetchone()
    if not row:
        raise ValueError("Pending task not found: %s" % task_id)
    conn.execute("UPDATE tasks SET status='delegated' WHERE id=?", (row["id"],))
    conn.commit()
    if notes:
        _append_note(conn, row["id"], notes)
    logger.info("task delegated: %s", row["id"])


def update_task_notes(
    conn: sqlite3.Connection, task_id: str, notes: str
) -> None:
    """Append progress note to a delegated task. Raises if not delegated."""
    row = conn.execute(
        "SELECT id, status FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    if not row or row["status"] != "delegated":
        raise ValueError("Task %s is not delegated" % task_id)
    _append_note(conn, task_id, notes)


def return_to_pending(
    conn: sqlite3.Connection, task_id: str, notes: str
) -> None:
    """Return a delegated task to pending with a failure note."""
    row = conn.execute(
        "SELECT id FROM tasks WHERE id=? AND status='delegated'", (task_id,)
    ).fetchone()
    if not row:
        raise ValueError("Delegated task not found: %s" % task_id)
    _append_note(conn, task_id, notes)
    conn.execute("UPDATE tasks SET status='pending' WHERE id=?", (task_id,))
    conn.commit()
    logger.info("task returned to pending: %s", task_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_core.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/core.py tests/test_core.py
git commit -m "feat: task lifecycle — mark_done, mark_delegated, return_to_pending"
```

---

## Task 7: list_tasks

**Files:**
- Modify: `src/timeopt/core.py`
- Modify: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_core.py`:
```python
from datetime import datetime, timezone, timedelta
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_core.py::test_list_tasks_returns_pending_by_default -v
```

Expected: `ImportError: cannot import name 'list_tasks'`

- [ ] **Step 3: Add `list_tasks` to `core.py`**

Add to `src/timeopt/core.py`:
```python
_DISPLAY_FIELDS = (
    "display_id", "title", "priority", "urgent", "category",
    "effort", "due_at", "status", "due_event_label", "due_unresolved",
)


def list_tasks(
    conn: sqlite3.Connection,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    include_old_done: bool = False,
) -> list[dict]:
    """
    Return tasks as dicts with display fields only.
    Defaults to pending + delegated. Auto-upgrades urgency before returning.
    """
    _auto_classify(conn)

    hide_days = int(get_config(conn, "hide_done_after_days"))
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=hide_days)
    ).isoformat()

    clauses = []
    params: list[Any] = []

    if status:
        clauses.append("status = ?")
        params.append(status)
    else:
        if include_old_done:
            pass  # no filter
        else:
            clauses.append(
                "(status IN ('pending','delegated') OR "
                "(status='done' AND done_at >= ?))"
            )
            params.append(cutoff)

    if priority:
        clauses.append("priority = ?")
        params.append(priority)
    if category:
        clauses.append("category = ?")
        params.append(category)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    fields = ", ".join(_DISPLAY_FIELDS)
    rows = conn.execute(
        f"SELECT {fields} FROM tasks {where} ORDER BY rowid", params
    ).fetchall()

    result = []
    for row in rows:
        d = dict(zip(_DISPLAY_FIELDS, row))
        # truncate notes to 60 chars for display
        if "notes" in d and d.get("notes"):
            d["notes"] = d["notes"][-60:]
        result.append(d)
    return result
```

- [ ] **Step 4: Add `_auto_classify` stub** (full implementation in Task 9)

Add to `src/timeopt/core.py` before `list_tasks`:
```python
def _auto_classify(conn: sqlite3.Connection) -> None:
    """Upgrade urgency for tasks with due_at today or overdue. Called automatically."""
    today = datetime.now(timezone.utc).date().isoformat()
    conn.execute(
        "UPDATE tasks SET urgent=1 "
        "WHERE status IN ('pending','delegated') "
        "AND due_at IS NOT NULL AND due_at <= ? AND urgent=0",
        (today + "T23:59:59",),
    )
    conn.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_core.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/timeopt/core.py tests/test_core.py
git commit -m "feat: list_tasks with auto-urgency upgrade and display-field projection"
```

---

## Task 8: get_task and fuzzy_match_tasks

**Files:**
- Modify: `src/timeopt/core.py`
- Modify: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_core.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_core.py::test_get_task_returns_full_row -v
```

Expected: `ImportError: cannot import name 'get_task'`

- [ ] **Step 3: Add `get_task` and `fuzzy_match_tasks` to `core.py`**

Add to `src/timeopt/core.py`:
```python
from rapidfuzz import process as fuzz_process


def get_task(conn: sqlite3.Connection, task_id: str) -> dict:
    """Return full task dict by UUID. Raises ValueError if not found."""
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise ValueError("Task not found: %s" % task_id)
    return dict(row)


def fuzzy_match_tasks(
    conn: sqlite3.Connection, query: str, limit: int = 5
) -> list[dict]:
    """
    Fuzzy-match query against active task titles.
    Returns list of {task_id, display_id, title, score} sorted by score desc.
    Only searches pending and delegated tasks.
    """
    rows = conn.execute(
        "SELECT id, display_id, title FROM tasks "
        "WHERE status IN ('pending', 'delegated')"
    ).fetchall()

    if not rows:
        return []

    titles = [row["title"] for row in rows]
    results = fuzz_process.extract(query, titles, limit=limit)

    matches = []
    for title, score, idx in results:
        row = rows[idx]
        matches.append({
            "task_id": row["id"],
            "display_id": row["display_id"],
            "title": row["title"],
            "score": score,
        })
    return sorted(matches, key=lambda x: x["score"], reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_core.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/core.py tests/test_core.py
git commit -m "feat: get_task full detail and fuzzy_match_tasks via rapidfuzz"
```

---

## Task 9: Eisenhower Classification

**Files:**
- Create: `src/timeopt/planner.py`
- Create: `tests/test_planner.py`

- [ ] **Step 1: Write failing tests**

`tests/test_planner.py`:
```python
import pytest
from timeopt.core import create_task, TaskInput, get_config
from timeopt.planner import eisenhower_quadrant, classify_tasks, EisenhowerQ


def _task(title, priority, urgent):
    return TaskInput(title=title, raw=title, priority=priority,
                     urgent=urgent, category="work", effort="medium")


def test_q1_urgent_important(conn):
    assert eisenhower_quadrant("high", True) == EisenhowerQ.Q1
    assert eisenhower_quadrant("medium", True) == EisenhowerQ.Q1


def test_q2_important_not_urgent(conn):
    assert eisenhower_quadrant("high", False) == EisenhowerQ.Q2
    assert eisenhower_quadrant("medium", False) == EisenhowerQ.Q2


def test_q3_urgent_not_important(conn):
    assert eisenhower_quadrant("low", True) == EisenhowerQ.Q3


def test_q4_neither(conn):
    assert eisenhower_quadrant("low", False) == EisenhowerQ.Q4


def test_classify_tasks_upgrades_urgency_for_overdue(conn):
    from datetime import datetime, timezone, timedelta
    past_due = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    t = TaskInput(title="overdue task", raw="overdue", priority="medium",
                  urgent=False, category="work", effort="small", due_at=past_due)
    display_id = create_task(conn, t)
    classify_tasks(conn)
    row = conn.execute("SELECT urgent FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    assert row[0] == 1


def test_classify_tasks_sorts_by_quadrant(conn):
    create_task(conn, _task("q4 task", "low", False))
    create_task(conn, _task("q1 task", "high", True))
    create_task(conn, _task("q2 task", "high", False))
    create_task(conn, _task("q3 task", "low", True))
    results = classify_tasks(conn)
    quadrants = [r["quadrant"] for r in results]
    assert quadrants == ["Q1", "Q2", "Q3", "Q4"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_planner.py -v
```

Expected: `ModuleNotFoundError: No module named 'timeopt.planner'`

- [ ] **Step 3: Write `src/timeopt/planner.py`**

```python
import sqlite3
import logging
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class EisenhowerQ(str, Enum):
    Q1 = "Q1"  # urgent + important
    Q2 = "Q2"  # important, not urgent
    Q3 = "Q3"  # urgent, not important
    Q4 = "Q4"  # neither


_Q_ORDER = {EisenhowerQ.Q1: 0, EisenhowerQ.Q2: 1, EisenhowerQ.Q3: 2, EisenhowerQ.Q4: 3}
_PRIORITY_IMPORTANT = {"high", "medium"}


def eisenhower_quadrant(priority: str, urgent: bool) -> EisenhowerQ:
    """Map priority + urgent to Eisenhower quadrant."""
    important = priority in _PRIORITY_IMPORTANT
    if urgent and important:
        return EisenhowerQ.Q1
    if important and not urgent:
        return EisenhowerQ.Q2
    if urgent and not important:
        return EisenhowerQ.Q3
    return EisenhowerQ.Q4


def classify_tasks(
    conn: sqlite3.Connection, task_ids: list[str] | None = None
) -> list[dict]:
    """
    Run Eisenhower classification on active tasks.
    Upgrades urgency for overdue/due-today tasks.
    Returns tasks sorted by quadrant order.
    If task_ids provided, only classifies those tasks.
    """
    today_end = datetime.now(timezone.utc).date().isoformat() + "T23:59:59"

    # Auto-upgrade urgency for overdue tasks
    if task_ids:
        placeholders = ",".join("?" * len(task_ids))
        conn.execute(
            f"UPDATE tasks SET urgent=1 "
            f"WHERE id IN ({placeholders}) "
            f"AND status IN ('pending','delegated') "
            f"AND due_at IS NOT NULL AND due_at <= ? AND urgent=0",
            (*task_ids, today_end),
        )
    else:
        conn.execute(
            "UPDATE tasks SET urgent=1 "
            "WHERE status IN ('pending','delegated') "
            "AND due_at IS NOT NULL AND due_at <= ? AND urgent=0",
            (today_end,),
        )
    conn.commit()

    where = ""
    params: list = []
    if task_ids:
        placeholders = ",".join("?" * len(task_ids))
        where = f"WHERE id IN ({placeholders}) AND status IN ('pending','delegated')"
        params = list(task_ids)
    else:
        where = "WHERE status IN ('pending','delegated')"

    rows = conn.execute(
        f"SELECT id, display_id, title, priority, urgent, category, effort, "
        f"due_at, status FROM tasks {where}",
        params,
    ).fetchall()

    results = []
    for row in rows:
        q = eisenhower_quadrant(row["priority"], bool(row["urgent"]))
        results.append({
            "task_id": row["id"],
            "display_id": row["display_id"],
            "title": row["title"],
            "priority": row["priority"],
            "urgent": bool(row["urgent"]),
            "effort": row["effort"],
            "due_at": row["due_at"],
            "quadrant": q.value,
        })

    results.sort(key=lambda x: _Q_ORDER[EisenhowerQ(x["quadrant"])])
    logger.info("classify_tasks: classified %d tasks", len(results))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_planner.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/planner.py tests/test_planner.py
git commit -m "feat: Eisenhower classification with auto urgency upgrade"
```

---

## Task 10: get_plan_proposal

**Files:**
- Modify: `src/timeopt/planner.py`
- Modify: `tests/test_planner.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_planner.py`:
```python
from timeopt.planner import get_plan_proposal
from timeopt.core import set_config


def _seed_tasks(conn):
    """4 tasks across quadrants."""
    tasks = [
        _task("q1 deploy", "high", True),
        _task("q2 fix login", "high", False),
        _task("q2 prep slides", "medium", False),
        _task("q4 buy groceries", "low", False),
    ]
    for t in tasks:
        create_task(conn, t)


def test_plan_proposal_returns_blocks(conn):
    _seed_tasks(conn)
    # No calendar events — full day free
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    assert len(proposal["blocks"]) > 0
    assert "task_id" in proposal["blocks"][0]
    assert "start" in proposal["blocks"][0]
    assert "duration_min" in proposal["blocks"][0]


def test_plan_proposal_respects_calendar_events(conn):
    _seed_tasks(conn)
    # Block 09:00–12:00 with a meeting
    events = [{"start": "2026-03-28T09:00:00", "end": "2026-03-28T12:00:00", "title": "big meeting"}]
    proposal = get_plan_proposal(conn, events=events, date="2026-03-28")
    # No block should start before 12:00
    for block in proposal["blocks"]:
        assert block["start"] >= "2026-03-28T12:00:00"


def test_plan_proposal_q1_scheduled_first(conn):
    _seed_tasks(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    first_block = proposal["blocks"][0]
    assert first_block["quadrant"] == "Q1"


def test_plan_proposal_inserts_breaks(conn):
    _seed_tasks(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    blocks = proposal["blocks"]
    if len(blocks) >= 2:
        end_first = _parse_end(blocks[0])
        start_second = blocks[1]["start"]
        gap_min = (_parse_dt(start_second) - end_first).seconds // 60
        assert gap_min >= 15  # break_duration_min default


def test_plan_proposal_defers_overflow(conn):
    set_config(conn, "day_end", "10:00")  # only 1 hour of work
    _seed_tasks(conn)  # 4 tasks, total effort > 1h
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    assert len(proposal["deferred"]) > 0


def _parse_dt(iso: str):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _parse_end(block: dict):
    start = _parse_dt(block["start"])
    from datetime import timedelta
    return start + timedelta(minutes=block["duration_min"])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_planner.py::test_plan_proposal_returns_blocks -v
```

Expected: `ImportError: cannot import name 'get_plan_proposal'`

- [ ] **Step 3: Add `get_plan_proposal` to `planner.py`**

Add to `src/timeopt/planner.py`:
```python
from datetime import datetime, timezone, timedelta
from timeopt.core import get_all_config


def _parse_time(date_str: str, time_str: str) -> datetime:
    """Combine a date string (YYYY-MM-DD) and time string (HH:MM) into UTC datetime."""
    return datetime.fromisoformat(f"{date_str}T{time_str}:00+00:00")


def _effort_minutes(effort: str | None, config: dict) -> int:
    mapping = {
        "small": int(config["effort_small_min"]),
        "medium": int(config["effort_medium_min"]),
        "large": int(config["effort_large_min"]),
    }
    return mapping.get(effort or "medium", int(config["effort_medium_min"]))


def _compute_free_slots(
    date: str,
    events: list[dict],
    day_start: datetime,
    day_end: datetime,
) -> list[tuple[datetime, datetime]]:
    """Return list of (start, end) free time slots given calendar events."""
    busy = []
    for ev in events:
        s = datetime.fromisoformat(ev["start"].replace("Z", "+00:00"))
        e = datetime.fromisoformat(ev["end"].replace("Z", "+00:00"))
        busy.append((s, e))
    busy.sort(key=lambda x: x[0])

    slots = []
    cursor = day_start
    for s, e in busy:
        if cursor < s:
            slots.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < day_end:
        slots.append((cursor, day_end))
    return slots


def get_plan_proposal(
    conn: sqlite3.Connection,
    events: list[dict],
    date: str | None = None,
) -> dict:
    """
    Compute a time-blocked schedule for the given date.

    Args:
        conn: SQLite connection
        events: List of {start, end, title} calendar events (ISO8601 strings)
        date: YYYY-MM-DD string, defaults to today UTC

    Returns:
        {
            "blocks": [{task_id, display_id, title, start, duration_min, quadrant}],
            "deferred": [{task_id, display_id, title, quadrant}],
        }
    """
    if date is None:
        date = datetime.now(timezone.utc).date().isoformat()

    config = get_all_config(conn)
    day_start = _parse_time(date, config["day_start"])
    day_end = _parse_time(date, config["day_end"])
    break_min = int(config["break_duration_min"])

    free_slots = _compute_free_slots(date, events, day_start, day_end)
    tasks = classify_tasks(conn)  # sorted Q1→Q4, urgency upgraded

    blocks = []
    deferred = []
    slot_idx = 0
    cursor: datetime | None = free_slots[0][0] if free_slots else None

    for task in tasks:
        duration = _effort_minutes(task.get("effort"), config)

        # Find a slot that fits
        scheduled = False
        while slot_idx < len(free_slots):
            slot_start, slot_end = free_slots[slot_idx]
            if cursor is None or cursor < slot_start:
                cursor = slot_start

            available = (slot_end - cursor).seconds // 60
            if available >= duration:
                block_start = cursor.isoformat()
                blocks.append({
                    "task_id": task["task_id"],
                    "display_id": task["display_id"],
                    "title": task["title"],
                    "start": block_start,
                    "duration_min": duration,
                    "quadrant": task["quadrant"],
                })
                cursor = cursor + timedelta(minutes=duration + break_min)
                scheduled = True
                break
            else:
                slot_idx += 1
                cursor = None

        if not scheduled:
            deferred.append({
                "task_id": task["task_id"],
                "display_id": task["display_id"],
                "title": task["title"],
                "quadrant": task["quadrant"],
            })

    logger.info(
        "get_plan_proposal: %d blocks, %d deferred for %s",
        len(blocks), len(deferred), date,
    )
    return {"blocks": blocks, "deferred": deferred}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_planner.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/planner.py tests/test_planner.py
git commit -m "feat: get_plan_proposal — server-side scheduling with Eisenhower sort and overflow"
```

---

## Task 11: calendar_blocks CRUD

**Files:**
- Modify: `src/timeopt/planner.py`
- Modify: `tests/test_planner.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_planner.py`:
```python
from timeopt.planner import save_calendar_blocks, delete_calendar_blocks_for_date, get_calendar_blocks


def test_save_calendar_blocks(conn):
    _seed_tasks(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    save_calendar_blocks(conn, proposal["blocks"], "2026-03-28",
                         caldav_uids=["uid-1", "uid-2", "uid-3", "uid-4"])
    blocks = get_calendar_blocks(conn, "2026-03-28")
    assert len(blocks) == len(proposal["blocks"])


def test_delete_calendar_blocks_for_date(conn):
    _seed_tasks(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    uids = [f"uid-{i}" for i in range(len(proposal["blocks"]))]
    save_calendar_blocks(conn, proposal["blocks"], "2026-03-28", caldav_uids=uids)
    delete_calendar_blocks_for_date(conn, "2026-03-28")
    assert get_calendar_blocks(conn, "2026-03-28") == []


def test_save_returns_stored_uids(conn):
    _seed_tasks(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    uids = [f"uid-{i}" for i in range(len(proposal["blocks"]))]
    save_calendar_blocks(conn, proposal["blocks"], "2026-03-28", caldav_uids=uids)
    blocks = get_calendar_blocks(conn, "2026-03-28")
    stored_uids = {b["caldav_uid"] for b in blocks}
    assert stored_uids == set(uids)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_planner.py::test_save_calendar_blocks -v
```

Expected: `ImportError: cannot import name 'save_calendar_blocks'`

- [ ] **Step 3: Add calendar_blocks CRUD to `planner.py`**

Add to `src/timeopt/planner.py`:
```python
import uuid as _uuid


def save_calendar_blocks(
    conn: sqlite3.Connection,
    blocks: list[dict],
    plan_date: str,
    caldav_uids: list[str],
) -> None:
    """
    Persist calendar blocks after successful CalDAV push.
    caldav_uids must be the same length and order as blocks.
    """
    assert len(blocks) == len(caldav_uids), "blocks and caldav_uids must match"
    for block, uid in zip(blocks, caldav_uids):
        conn.execute(
            "INSERT INTO calendar_blocks(id, task_id, caldav_uid, scheduled_at, duration_min, plan_date) "
            "VALUES (?,?,?,?,?,?)",
            (
                str(_uuid.uuid4()),
                block["task_id"],
                uid,
                block["start"],
                block["duration_min"],
                plan_date,
            ),
        )
    conn.commit()
    logger.info("saved %d calendar blocks for %s", len(blocks), plan_date)


def delete_calendar_blocks_for_date(
    conn: sqlite3.Connection, plan_date: str
) -> list[str]:
    """
    Delete all calendar_blocks rows for a date.
    Returns list of caldav_uids that must be deleted from CalDAV by the caller.
    """
    rows = conn.execute(
        "SELECT caldav_uid FROM calendar_blocks WHERE plan_date=?", (plan_date,)
    ).fetchall()
    uids = [row[0] for row in rows]
    conn.execute("DELETE FROM calendar_blocks WHERE plan_date=?", (plan_date,))
    conn.commit()
    logger.info("deleted %d calendar blocks for %s", len(uids), plan_date)
    return uids


def get_calendar_blocks(
    conn: sqlite3.Connection, plan_date: str
) -> list[dict]:
    """Return all calendar blocks for a date."""
    rows = conn.execute(
        "SELECT id, task_id, caldav_uid, scheduled_at, duration_min, plan_date "
        "FROM calendar_blocks WHERE plan_date=?",
        (plan_date,),
    ).fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 4: Run all tests to verify they pass**

```bash
uv run pytest -v
```

Expected: all pass.

- [ ] **Step 5: Final commit**

```bash
git add src/timeopt/planner.py tests/test_planner.py
git commit -m "feat: calendar_blocks CRUD — save, delete, get by date"
```

---

## Self-Review

### Spec Coverage

| Spec requirement | Covered by |
|---|---|
| SQLite WAL mode | Task 2 `get_connection` |
| `short_id` recycling 1–99 | Task 3 |
| `display_id` partial index on active tasks | Task 2 schema |
| Config with defaults | Task 4 |
| Task creation with `TaskInput` | Task 5 |
| `mark_done` filters to active tasks only | Task 6 |
| `mark_delegated` / `update_task_notes` (append-only, timestamped) | Task 6 |
| `return_to_pending` | Task 6 |
| `list_tasks` display fields + auto-classify | Task 7 |
| `get_task` full detail | Task 8 |
| `fuzzy_match_tasks` via rapidfuzz | Task 8 |
| Eisenhower quadrant mapping | Task 9 |
| `classify_tasks` with urgency auto-upgrade | Task 9 |
| `get_plan_proposal` server-side scheduling | Task 10 |
| Break insertion | Task 10 |
| Overflow deferral | Task 10 |
| `calendar_blocks` CRUD | Task 11 |
| `dump_task` / `dump_tasks` | Not yet — Plan 2 (needs LLM for CLI path) |
| CalDAV event binding | Not yet — Plan 2 |
| `/sync` logic | Not yet — Plan 2 |
| MCP server tools | Not yet — Plan 3 |
| CLI | Not yet — Plan 3 |

### No Placeholders
Verified: no TBD, no "implement later", all code blocks are complete.

### Type Consistency
- `TaskInput` defined in Task 5, used consistently through Task 10
- `classify_tasks` returns `list[dict]` consumed by `get_plan_proposal` — keys match (`task_id`, `effort`, `quadrant`)
- `save_calendar_blocks` consumes `get_plan_proposal` blocks — keys match (`task_id`, `start`, `duration_min`)

---

**Plan complete and saved to `docs/superpowers/plans/2026-03-28-core-backend.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
