# E2E Testing — Notes

Analysis of the two e2e test layers missing from the current suite (196 tests, all passing as of 2026-04-01).

---

## What "e2e" means here

Current tests are unit + integration:
- `test_server.py` — imports server functions directly, no JSON-RPC
- `test_cli.py` — uses Click's `CliRunner` (in-process, no real subprocess)

Neither layer catches: entry point misconfiguration, import errors at startup, FastMCP wiring bugs, JSON-RPC schema mismatches.

---

## Layer 1: CLI subprocess tests

**File:** `tests/test_e2e_cli.py`

Spawn real binary via `subprocess.run(["uv", "run", "timeopt", ...])`.
Set `TIMEOPT_DB` env var to a temp file per test.

### What to cover

| Test | Command | Assert |
|------|---------|--------|
| Binary runs | `timeopt tasks` | exit 0, "No tasks" |
| Dump + list | `timeopt tasks` after seeding via subprocess | task appears |
| Done flow | `timeopt done <query>` | exit 0, ✓ in output |
| Config round-trip | `timeopt config set` / `config get` | value persisted |
| Plan (no caldav) | `timeopt plan --date 2026-04-01` | exit 0 |
| Invalid date | `timeopt plan --date bad` | exit != 0 |

### Fixture pattern

```python
@pytest.fixture
def e2e_db(tmp_path):
    db = str(tmp_path / "e2e.db")
    env = {**os.environ, "TIMEOPT_DB": db}
    return db, env

def run(args, env):
    return subprocess.run(
        ["uv", "run", "timeopt"] + args,
        capture_output=True, text=True, env=env,
        cwd="/home/claude/workdirs/timeopt",
    )
```

### Gotchas

- `uv run` adds startup latency (~200ms). Tests are slow vs unit tests — mark with `@pytest.mark.e2e` and exclude from default run.
- Seed data must also go through subprocess (to use the real entry point), or directly write to the DB file via `db.get_connection(db_path)`.
- The binary name is `timeopt` (from `pyproject.toml` `[project.scripts]`). Verify with `uv run timeopt --help` before writing tests.

---

## Layer 2: MCP server protocol tests

**File:** `tests/test_e2e_server.py`

Spawn `uv run timeopt-server` and communicate over stdio using the MCP client from the `mcp` library.

### Dependency

```bash
uv add --dev pytest-asyncio
```

`mcp` is already a project dependency (it provides `fastmcp`), so `mcp.client.stdio` is available.

### Fixture pattern

```python
import asyncio, os, pytest
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

@pytest.fixture
def server_params(tmp_path):
    return StdioServerParameters(
        command="uv",
        args=["run", "timeopt-server"],
        env={**os.environ, "TIMEOPT_DB": str(tmp_path / "e2e.db")},
    )
```

### What to cover

| Test | Tool(s) called | Assert |
|------|---------------|--------|
| `list_tools` | (protocol) | 19 tools present, names match expected |
| Read: `list_tasks` | `list_tasks` | returns `{"tasks": []}` on empty DB |
| Write: `dump_task` | `dump_task` → `list_tasks` | task appears in list |
| Status: `mark_done` | `dump_task` → `mark_done` → `list_tasks` | task gone from pending |
| Config: `get_config` | `get_config(key="day_start")` | returns `{"value": "09:00"}` |
| Plan: `get_plan_proposal` | seed tasks → `get_plan_proposal` | blocks non-empty |
| CalDAV: `get_calendar_events` | (no config) | returns warning, not error |

### Gotchas

- `stdio_client` returns `(read_stream, write_stream)` — must be used as async context manager.
- Each test needs its own server instance (separate `tmp_path` DB) for isolation.
- `pytest-asyncio` requires `asyncio_mode = "auto"` in `pyproject.toml` or `@pytest.mark.asyncio` on each test.
- Server startup is slow. Use a session-scoped fixture if tests share state, or accept per-test startup cost.
- `result.content[0].text` from `call_tool` is a JSON string — parse with `json.loads()`. `result.structuredContent` also contains the parsed dict directly (FastMCP 3.x).
- FastMCP does NOT add an extra `{"result": ...}` wrapper — tool return values are serialized directly. The `content[0].text` is the raw JSON of what the tool returned.
- No `@pytest.mark.asyncio` needed on individual tests when `asyncio_mode = "auto"` is set — async test functions are picked up automatically.
- `StdioServerParameters` accepts a `cwd` kwarg — use `PROJECT_ROOT` to ensure `uv run` resolves the virtualenv correctly.
- Each test function opens its own server via `stdio_client` — no shared session fixture needed for these 7 tests (acceptable overhead).

### Verifying tool count

Actual tool count is **18** (CLAUDE.md says 19 — off by one, never corrected):
`dump_task`, `dump_tasks`, `get_dump_templates`, `list_tasks`, `get_task`, `fuzzy_match_tasks`, `mark_done`, `mark_delegated`, `update_task_notes`, `return_to_pending`, `classify_tasks`, `get_plan_proposal`, `push_calendar_blocks`, `get_calendar_events`, `resolve_calendar_reference`, `sync_calendar`, `get_config`, `set_config`

Confirmed via `grep -c "@mcp.tool" src/timeopt/server.py` → 18.

---

## Execution order

1. Add `pytest-asyncio` dev dependency
2. Write `test_e2e_cli.py` (simpler, no async)
3. Smoke-test MCP server manually: `echo '{}' | uv run timeopt-server` to confirm it starts
4. Write `test_e2e_server.py` with just `list_tools` first
5. Expand to full tool coverage

## pytest config

Add to `pyproject.toml` to exclude e2e from default run:

```toml
[tool.pytest.ini_options]
markers = ["e2e: end-to-end tests (slow, spawn subprocess)"]
addopts = "-m 'not e2e'"
```

Run e2e explicitly: `uv run pytest -m e2e -v`
