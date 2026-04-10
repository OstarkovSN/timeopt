# tests/ — Test Context

## Run Tests

```bash
uv run pytest tests/ -v               # all tests
uv run pytest tests/test_core.py -v   # single file
uv run pytest -k test_name -v         # single test
```

## Fixture Patterns

**`conn` fixture (`conftest.py`):** In-memory SQLite DB with schema. Use for unit tests that call `core.*` or `planner.*` functions directly.

```python
def test_something(conn):
    core.create_task(conn, core.TaskInput(...))
```

**`server_env` / `cli_env` fixtures (in test_server.py / test_cli.py):** Create a real DB file in `tmp_path`, then patch `TIMEOPT_DB` env var so the server/CLI module opens that file. Use for integration-style tests that call server tools or CLI commands.

```python
@pytest.fixture
def server_env(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = db.get_connection(db_path)
    db.create_schema(conn)
    conn.close()
    with patch.dict(os.environ, {"TIMEOPT_DB": db_path}):
        yield db_path
```

Do NOT use the `conn` fixture in server/CLI tests — server tools open their own connection via `_open_conn()`.

## Mock Conventions

**CalDAV:** Patch at `timeopt.server._get_caldav`, not at the `caldav` library level. Return a `MagicMock` with `.get_events()`, `.create_event()`, `.delete_event()` methods.

```python
mock_caldav = MagicMock()
mock_caldav.get_events.return_value = [
    CalendarEvent(start="2026-04-01T09:00:00Z", end="2026-04-01T10:00:00Z",
                  title="Team sync", uid="abc-123")
]
with patch("timeopt.server._get_caldav", return_value=mock_caldav):
    result = get_calendar_events()
```

**LLM client:** Patch at `timeopt.cli._get_llm_client` (for CLI tests) or pass a `MagicMock` with `.complete()` method directly (for core unit tests).

**`CalendarEvent` objects vs dicts:** `caldav_client.get_events` returns `CalendarEvent` dataclass objects. `core.sync_bound_tasks` and `core.resolve_calendar_reference` also expect `CalendarEvent` objects (they access `.uid`, `.title`, `.start`, `.end` attributes). The server converts them to dicts before passing to `planner.get_plan_proposal`. Match the interface expected by the function under test.

## Seeding Tasks

```python
# Direct (unit tests with conn fixture)
core.dump_task(conn, core.TaskInput(
    title="fix login bug", raw="fix login bug",
    priority="high", urgent=False, category="work", effort="medium"
))

# Via server (server_env fixture) — also tests dump_task server tool
from timeopt.server import dump_task
dump_task(task={"title": "fix login", "raw": "fix login",
                "priority": "high", "urgent": False,
                "category": "work", "effort": "medium"})
```

## What's Tested Where

| File | Covers |
|---|---|
| `test_db.py` | Schema creation, constraint definitions |
| `test_core.py` | Task CRUD, config, list/filter |
| `test_core_integrations.py` | dump templates, resolve_calendar_reference, sync |
| `test_planner.py` | Eisenhower classification, scheduling, free-slot computation |
| `test_push_blocks.py` | push_calendar_blocks (full CalDAV failure case) |
| `test_caldav.py` | CalDAVClient, connection failure |
| `test_llm.py` | LLM client success paths |
| `test_server.py` | 19 server tools; CalDAV tools tested only in "not configured" state |
| `test_cli.py` | CLI commands via CliRunner |
| `test_sync.py` | sync_bound_tasks |

See `@docs/superpowers/notes/test-coverage-gaps.md` for prioritized list of missing tests.
