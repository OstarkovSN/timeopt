# Timeopt Interfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Core API and Integrations into the MCP server, click CLI, slash command templates, and plugin configuration files — making timeopt usable from both Claude Code and the terminal.

**Architecture:** `server.py` exposes all Core API functions as fastmcp tools, reading DB path from `TIMEOPT_DB` env var (default `~/.timeopt/tasks.db`). `cli.py` is a click app that calls Core API directly; `dump` and `plan` invoke LLMClient for NLP. Slash commands are markdown prompt templates in `.claude/commands/`. Plugin config files wire everything together for Claude Code.

**Prerequisites:** Plans 1 (Core Backend) and 2 (Integrations) must be fully implemented and all tests passing.

**Tech Stack:** `fastmcp`, `click`, Python 3.11+

---

## File Map

| File | Responsibility |
|---|---|
| `src/timeopt/server.py` | MCP server — all tool wrappers, CalDAV/DB helpers, `main()` entry |
| `src/timeopt/cli.py` | Click CLI — all commands, LLM init, output formatting |
| `src/timeopt/core.py` (modify) | Add `cli_dump(conn, llm_client, raw_text)` for CLI brain dump |
| `.claude/commands/dump.md` | Brain dump slash command |
| `.claude/commands/tasks.md` | View tasks slash command |
| `.claude/commands/plan.md` | Daily plan slash command |
| `.claude/commands/done.md` | Mark done slash command |
| `.claude/commands/check-urgent.md` | Check urgent + delegate slash command |
| `.claude/commands/sync.md` | Calendar sync slash command |
| `.claude/commands/history.md` | View history slash command |
| `.claude-plugin/plugin.json` | Plugin metadata |
| `.mcp.json` | MCP server config for Claude Code |
| `tests/test_server.py` | MCP tool wiring tests (env-patched file DB) |
| `tests/test_cli.py` | CLI command tests via click CliRunner |

---

## Task 1: MCP Server — Setup + Task/Config Tools

**Files:**
- Create: `src/timeopt/server.py`
- Create: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

`tests/test_server.py`:
```python
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
    task = get_task(task_id=dumped["display_id"])
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_server.py -v
```

Expected: `ModuleNotFoundError: No module named 'timeopt.server'`

- [ ] **Step 3: Write `src/timeopt/server.py` (setup + task/config tools)**

```python
import logging
import os
from datetime import date as _date_type, datetime as _datetime
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

from timeopt import core, db, planner
from timeopt.caldav_client import CalDAVClient
from timeopt.core import TaskInput

logger = logging.getLogger(__name__)
mcp = FastMCP("timeopt")

_DEFAULT_DB = str(Path.home() / ".timeopt" / "tasks.db")


def _db_path() -> str:
    return os.environ.get("TIMEOPT_DB", _DEFAULT_DB)


def _open_conn():
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = db.get_connection(path)
    db.create_schema(conn)
    return conn


def _parse_date(date_str: Optional[str]) -> _date_type:
    if date_str:
        return _datetime.fromisoformat(date_str).date()
    return _date_type.today()


def _get_caldav(conn) -> Optional[CalDAVClient]:
    url = core.get_config(conn, "caldav_url") or "https://caldav.yandex.ru"
    username = core.get_config(conn, "caldav_username")
    password = core.get_config(conn, "caldav_password")
    read_cals = core.get_config(conn, "caldav_read_calendars") or "all"
    tasks_cal = core.get_config(conn, "caldav_tasks_calendar") or "Timeopt"
    if not username or not password:
        return None
    return CalDAVClient(
        url=url, username=username, password=password,
        read_calendars=read_cals, tasks_calendar=tasks_cal,
    )


def _dict_to_task_input(d: dict) -> TaskInput:
    return TaskInput(
        title=d.get("title", ""),
        raw=d.get("raw") or d.get("title", ""),
        priority=d.get("priority", "medium"),
        urgent=bool(d.get("urgent", False)),
        category=d.get("category", "other"),
        effort=d.get("effort") or None,
        due_at=d.get("due_at"),
        due_event_label=d.get("due_event_label"),
        due_event_uid=d.get("due_event_uid") or d.get("_resolved_event_uid"),
        due_event_offset_min=d.get("due_event_offset_min"),
        due_unresolved=bool(d.get("due_unresolved", False)),
    )


@mcp.tool()
def list_tasks(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    include_old_done: bool = False,
) -> dict:
    """List tasks. Defaults to pending + delegated, sorted by Eisenhower quadrant."""
    conn = _open_conn()
    try:
        return core.list_tasks(conn, status=status, priority=priority,
                               category=category, include_old_done=include_old_done)
    finally:
        conn.close()


@mcp.tool()
def get_task(task_id: str) -> dict:
    """Get full detail for a single task by UUID or display_id."""
    conn = _open_conn()
    try:
        return core.get_task(conn, task_id)
    finally:
        conn.close()


@mcp.tool()
def fuzzy_match_tasks(query: str) -> dict:
    """Fuzzy-match active task titles. Returns ranked candidates with scores."""
    conn = _open_conn()
    try:
        return core.fuzzy_match_tasks(conn, query)
    finally:
        conn.close()


@mcp.tool()
def mark_done(task_ids: list) -> dict:
    """Mark tasks as done. Accepts list of UUIDs or display_ids."""
    conn = _open_conn()
    try:
        return core.mark_done(conn, task_ids)
    finally:
        conn.close()


@mcp.tool()
def mark_delegated(task_id: str, notes: Optional[str] = None) -> dict:
    """Set task status to delegated. Optionally write an initial timestamped note."""
    conn = _open_conn()
    try:
        return core.mark_delegated(conn, task_id, notes)
    finally:
        conn.close()


@mcp.tool()
def update_task_notes(task_id: str, notes: str) -> dict:
    """Append a timestamped note to a delegated task. Returns error if task is not delegated."""
    conn = _open_conn()
    try:
        return core.update_task_notes(conn, task_id, notes)
    finally:
        conn.close()


@mcp.tool()
def return_to_pending(task_id: str, notes: str) -> dict:
    """Return a delegated task to pending with a failure note."""
    conn = _open_conn()
    try:
        return core.return_to_pending(conn, task_id, notes)
    finally:
        conn.close()


@mcp.tool()
def classify_tasks(task_ids: Optional[list] = None) -> dict:
    """Run Eisenhower classification. Returns quadrant assignments for all active tasks."""
    conn = _open_conn()
    try:
        return planner.classify_tasks(conn, task_ids)
    finally:
        conn.close()


@mcp.tool()
def get_config(key: Optional[str] = None) -> dict:
    """Get a config value by key. Omit key to return all config as a flat dict."""
    conn = _open_conn()
    try:
        if key:
            return {"key": key, "value": core.get_config(conn, key)}
        return core.get_all_config(conn)
    finally:
        conn.close()


@mcp.tool()
def set_config(key: str, value: str) -> dict:
    """Set a config value. Returns {ok, key, value}."""
    conn = _open_conn()
    try:
        core.set_config(conn, key, value)
        return {"ok": True, "key": key, "value": value}
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_server.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/server.py tests/test_server.py
git commit -m "feat: MCP server setup and task/config tools"
```

---

## Task 2: MCP Server — Brain Dump + Calendar + Planning Tools

**Files:**
- Modify: `src/timeopt/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_server.py`:
```python
def test_get_dump_templates(server_env):
    from timeopt.server import get_dump_templates
    result = get_dump_templates(fragments=["fix login bug", "deploy before noon"])
    assert "schema" in result
    assert "templates" in result
    assert len(result["templates"]) == 2
    # Simple task: no due_at pre-filled
    assert "due_at" not in result["templates"][0]
    # Time reference: due_at pre-filled
    assert "due_at" in result["templates"][1]


def test_dump_task_returns_id_and_display_id(server_env):
    from timeopt.server import dump_task
    result = dump_task(task={
        "raw": "prep report before meeting with Jeff",
        "title": "prep report",
        "priority": "high",
        "urgent": False,
        "category": "work",
        "effort": "large",
        "due_event_label": "meeting with Jeff",
        "due_event_offset_min": -30,
    })
    assert "display_id" in result
    assert "id" in result
    assert result["id"] is not None


def test_dump_tasks_batch(server_env):
    from timeopt.server import dump_tasks, list_tasks
    result = dump_tasks(tasks=[
        {"raw": "a", "title": "task a", "priority": "high",
         "urgent": False, "category": "work", "effort": "small"},
        {"raw": "b", "title": "task b", "priority": "low",
         "urgent": False, "category": "personal", "effort": "small"},
    ])
    assert result["count"] == 2
    assert len(result["display_ids"]) == 2
    assert len(list_tasks()["tasks"]) == 2


def test_get_calendar_events_no_caldav(server_env):
    from timeopt.server import get_calendar_events
    result = get_calendar_events()
    assert "events" in result
    # No CalDAV configured: empty list with warning
    assert result["events"] == []
    assert "warning" in result


def test_resolve_calendar_reference_no_caldav(server_env):
    from timeopt.server import resolve_calendar_reference
    result = resolve_calendar_reference(label="meeting with Jeff")
    assert "candidates" in result
    assert result["candidates"] == []
    assert "error" in result


def test_get_plan_proposal_no_caldav(server_env):
    from timeopt.server import dump_task, get_plan_proposal
    dump_task(task={"raw": "fix login", "title": "fix login",
                    "priority": "high", "urgent": False,
                    "category": "work", "effort": "medium"})
    result = get_plan_proposal(date="2026-03-28")
    assert "blocks" in result


def test_push_calendar_blocks_no_caldav(server_env):
    from timeopt.server import push_calendar_blocks
    result = push_calendar_blocks(blocks=[], date="2026-03-28")
    assert result["ok"] is False
    assert "error" in result


def test_sync_calendar_no_caldav(server_env):
    from timeopt.server import sync_calendar
    result = sync_calendar()
    assert result["ok"] is False
    assert "error" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_server.py::test_get_dump_templates -v
```

Expected: `AttributeError: module 'timeopt.server' has no attribute 'get_dump_templates'`

- [ ] **Step 3: Append brain dump + calendar + planning tools to `server.py`**

Append to `src/timeopt/server.py`:
```python
@mcp.tool()
def get_dump_templates(fragments: list) -> dict:
    """
    Build sparse task templates from raw text fragments for Claude to fill.
    Fetches CalDAV events for calendar reference detection (next 30 days).
    Returns {schema: {...}, templates: [{raw, title, priority: "?", ...}]}.
    """
    conn = _open_conn()
    try:
        caldav = _get_caldav(conn)
        events = []
        if caldav:
            try:
                events = caldav.get_events(_date_type.today().isoformat(), days=30)
            except Exception:
                logger.exception("get_dump_templates: CalDAV unavailable, skipping event detection")
        return core.get_dump_templates(fragments, events)
    finally:
        conn.close()


@mcp.tool()
def dump_task(task: dict) -> dict:
    """
    Save a single filled task object. Returns {display_id, id}.
    task should be a completed template returned by get_dump_templates.
    """
    conn = _open_conn()
    try:
        task_input = _dict_to_task_input(task)
        display_id = core.dump_task(conn, task_input)
        row = conn.execute("SELECT id FROM tasks WHERE display_id=?", (display_id,)).fetchone()
        return {"display_id": display_id, "id": row[0] if row else None}
    finally:
        conn.close()


@mcp.tool()
def dump_tasks(tasks: list) -> dict:
    """
    Save a batch of filled task objects. Returns {count, display_ids}.
    tasks should be completed templates from get_dump_templates.
    """
    conn = _open_conn()
    try:
        task_inputs = [_dict_to_task_input(t) for t in tasks]
        display_ids = core.dump_tasks(conn, task_inputs)
        return {"count": len(display_ids), "display_ids": display_ids}
    finally:
        conn.close()


@mcp.tool()
def resolve_calendar_reference(label: str, date_range: Optional[dict] = None) -> dict:
    """
    Fuzzy-match a textual event label against real CalDAV events.
    Returns {candidates: [{uid, title, start, end, score}]}.
    date_range: optional {start: "YYYY-MM-DD", end: "YYYY-MM-DD"} (default: next 30 days).
    """
    conn = _open_conn()
    try:
        caldav = _get_caldav(conn)
        if not caldav:
            return {"candidates": [], "error": "CalDAV not configured"}
        start_date = _date_type.today()
        days = 30
        if date_range:
            if date_range.get("start"):
                start_date = _datetime.fromisoformat(date_range["start"]).date()
            if date_range.get("end"):
                end_date = _datetime.fromisoformat(date_range["end"]).date()
                days = max(1, (end_date - start_date).days)
        events = caldav.get_events(start_date.isoformat(), days=days)
        match = core.resolve_calendar_reference(label, events)
        return {"candidates": [match] if match else []}
    finally:
        conn.close()


@mcp.tool()
def get_calendar_events(date: Optional[str] = None, days: int = 1) -> dict:
    """
    Fetch events from all configured read calendars. Read-only.
    Returns {events: [{title, start, end, uid}]}. Defaults to today.
    """
    conn = _open_conn()
    try:
        caldav = _get_caldav(conn)
        if not caldav:
            return {"events": [], "warning": "CalDAV not configured"}
        target = _parse_date(date).isoformat()
        events = caldav.get_events(target, days=days)
        return {"events": [
            {"title": e.title, "start": e.start, "end": e.end, "uid": e.uid}
            for e in events
        ]}
    finally:
        conn.close()


@mcp.tool()
def get_plan_proposal(date: Optional[str] = None) -> dict:
    """
    Server-side scheduling for the given date (default today).
    Fetches calendar events for free/busy; warns but proceeds if CalDAV unavailable.
    Returns {blocks: [{task_id, display_id, title, start, duration_min, quadrant}],
             deferred: [...]}.
    """
    conn = _open_conn()
    try:
        caldav = _get_caldav(conn)
        target = _parse_date(date).isoformat()
        events = []
        if caldav:
            try:
                events = caldav.get_events(target, days=1)
            except Exception:
                logger.exception("get_plan_proposal: CalDAV unavailable, planning without calendar")
        return planner.get_plan_proposal(conn, events, target)
    finally:
        conn.close()


@mcp.tool()
def push_calendar_blocks(blocks: list, date: Optional[str] = None) -> dict:
    """
    Transactional push: all CalDAV writes collected first, SQLite committed only on success.
    blocks: list of {task_id, display_id, title, start, duration_min, quadrant}.
    Returns {ok: bool, pushed: int}.
    """
    conn = _open_conn()
    try:
        caldav = _get_caldav(conn)
        if not caldav:
            return {"ok": False, "error": "CalDAV not configured"}
        target = _parse_date(date).isoformat()
        planner.push_calendar_blocks(conn, {"blocks": blocks}, target, caldav)
        return {"ok": True, "pushed": len(blocks)}
    finally:
        conn.close()


@mcp.tool()
def sync_calendar(date_range_days: int = 30) -> dict:
    """
    Sync calendar event bindings:
    1. Updates due_at for tasks bound to moved events (algorithmic).
    2. Attempts to resolve tasks with unresolved calendar references.
    Returns {ok, updated: [...], resolved: [...], unresolved_remaining: [...]}.
    """
    conn = _open_conn()
    try:
        caldav = _get_caldav(conn)
        if not caldav:
            return {"ok": False, "error": "CalDAV not configured"}
        events = caldav.get_events(_date_type.today().isoformat(), days=date_range_days)
        updated = core.sync_bound_tasks(conn, events)
        resolved = core.try_resolve_unresolved(conn, events)
        still_unresolved = core.get_unresolved_tasks(conn)
        return {
            "ok": True,
            "updated": updated,
            "resolved": resolved,
            "unresolved_remaining": still_unresolved,
        }
    finally:
        conn.close()


def main():
    mcp.run(transport="stdio")
```

- [ ] **Step 4: Run all server tests to verify they pass**

```bash
uv run pytest tests/test_server.py -v
```

Expected: 19 passed.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/server.py tests/test_server.py
git commit -m "feat: MCP server brain dump, calendar, and planning tools"
```

---

## Task 3: CLI — Setup + View Commands

**Files:**
- Create: `src/timeopt/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

`tests/test_cli.py`:
```python
import os
import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from timeopt import db, core


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def cli_env(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = db.get_connection(db_path)
    db.create_schema(conn)
    conn.close()
    with patch.dict(os.environ, {"TIMEOPT_DB": db_path}):
        yield db_path


def _seed(db_path, *task_kwargs_list):
    conn = db.get_connection(db_path)
    for kwargs in task_kwargs_list:
        core.dump_task(conn, core.TaskInput(**kwargs))
    conn.close()


def test_tasks_empty(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["tasks"])
    assert result.exit_code == 0
    assert "No tasks" in result.output


def test_tasks_shows_pending(runner, cli_env):
    from timeopt.cli import cli
    _seed(cli_env, {"title": "fix login bug", "raw": "fix login bug",
                    "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    result = runner.invoke(cli, ["tasks"])
    assert result.exit_code == 0
    assert "#1-fix-login-bug" in result.output
    assert "work" in result.output
    assert "high" in result.output


def test_tasks_status_filter(runner, cli_env):
    from timeopt.cli import cli
    _seed(cli_env, {"title": "fix login", "raw": "fix login",
                    "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    conn = db.get_connection(cli_env)
    row = conn.execute("SELECT id FROM tasks").fetchone()
    core.mark_done(conn, [row[0]])
    conn.close()
    result = runner.invoke(cli, ["tasks", "--status", "pending"])
    assert result.exit_code == 0
    assert "fix-login" not in result.output


def test_history_empty(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["history", "--today"])
    assert result.exit_code == 0
    assert "No completed tasks" in result.output


def test_history_shows_done(runner, cli_env):
    from timeopt.cli import cli
    _seed(cli_env, {"title": "fix login", "raw": "fix login",
                    "priority": "high", "urgent": False, "category": "work", "effort": "small"})
    conn = db.get_connection(cli_env)
    row = conn.execute("SELECT id FROM tasks").fetchone()
    core.mark_done(conn, [row[0]])
    conn.close()
    result = runner.invoke(cli, ["history", "--today"])
    assert result.exit_code == 0
    assert "#1-fix-login" in result.output


def test_config_get_default(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["config", "get", "day_start"])
    assert result.exit_code == 0
    assert "09:00" in result.output


def test_config_get_all(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["config", "get"])
    assert result.exit_code == 0
    assert "day_start" in result.output
    assert "day_end" in result.output


def test_config_set_and_get(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["config", "set", "day_start", "08:00"])
    assert result.exit_code == 0
    result = runner.invoke(cli, ["config", "get", "day_start"])
    assert "08:00" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: `ModuleNotFoundError: No module named 'timeopt.cli'`

- [ ] **Step 3: Write `src/timeopt/cli.py` (setup + view commands)**

```python
import logging
import os
import sys
from datetime import date as _date_type, timedelta
from pathlib import Path
from typing import Optional

import click

from timeopt import core, db, planner
from timeopt.core import TaskInput
from timeopt.llm_client import build_llm_client

logger = logging.getLogger(__name__)

_DEFAULT_DB = str(Path.home() / ".timeopt" / "tasks.db")


def _db_path() -> str:
    return os.environ.get("TIMEOPT_DB", _DEFAULT_DB)


def _open_conn():
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = db.get_connection(path)
    db.create_schema(conn)
    return conn


def _get_llm_client(conn):
    config = core.get_all_config(conn)
    try:
        return build_llm_client(config)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _get_caldav_client(conn):
    from timeopt.caldav_client import CalDAVClient
    url = core.get_config(conn, "caldav_url") or "https://caldav.yandex.ru"
    username = core.get_config(conn, "caldav_username")
    password = core.get_config(conn, "caldav_password")
    read_cals = core.get_config(conn, "caldav_read_calendars") or "all"
    tasks_cal = core.get_config(conn, "caldav_tasks_calendar") or "Timeopt"
    if not username or not password:
        return None
    return CalDAVClient(url=url, username=username, password=password,
                        read_calendars=read_cals, tasks_calendar=tasks_cal)


def _format_tags(task: dict) -> str:
    tags = []
    if task.get("category"):
        tags.append(task["category"])
    if task.get("priority"):
        tags.append(task["priority"])
    if task.get("urgent"):
        tags.append("urgent")
    if task.get("due_at"):
        tags.append(f"due {task['due_at'][:10]}")
    return f"[{', '.join(tags)}]" if tags else ""


def _print_task_line(task: dict, show_notes: bool = False):
    did = task.get("display_id", "")
    tags = _format_tags(task)
    notes_suffix = ""
    if show_notes and task.get("notes"):
        last_note = task["notes"].strip().split("\n")[-1]
        notes_suffix = f" — {last_note[:60]}"
    click.echo(f"  {did:<35} {tags}{notes_suffix}")


def _print_tasks(result: dict):
    tasks = result.get("tasks", [])
    pending = [t for t in tasks if t["status"] == "pending"]
    delegated = [t for t in tasks if t["status"] == "delegated"]

    if not pending and not delegated:
        click.echo("No tasks.")
        return

    if pending:
        click.echo(f"Pending ({len(pending)})")
        for t in pending:
            _print_task_line(t)

    if delegated:
        if pending:
            click.echo("")
        click.echo(f"Being handled by Claude ({len(delegated)})")
        for t in delegated:
            _print_task_line(t, show_notes=True)


@click.group()
def cli():
    """Timeopt — personal task manager with calendar integration."""
    pass


@cli.command()
@click.option("--status", default=None, help="Filter: pending, delegated, done")
@click.option("--priority", default=None, help="Filter: high, medium, low")
@click.option("--category", default=None, help="Filter by category")
@click.option("--all", "include_old_done", is_flag=True, default=False,
              help="Include done tasks older than hide_done_after_days")
def tasks(status, priority, category, include_old_done):
    """List tasks."""
    conn = _open_conn()
    try:
        result = core.list_tasks(conn, status=status, priority=priority,
                                  category=category, include_old_done=include_old_done)
        _print_tasks(result)
    finally:
        conn.close()


@cli.command()
@click.option("--today", "period", flag_value="today",
              help="Only today's completed tasks")
@click.option("--week", "period", flag_value="week",
              help="Tasks completed in the last 7 days")
@click.option("--all", "period", flag_value="all", default=True,
              help="All completed tasks")
def history(period):
    """View completed tasks."""
    conn = _open_conn()
    try:
        result = core.list_tasks(conn, status="done", include_old_done=True)
        done_tasks = result.get("tasks", [])

        if period == "today":
            today = _date_type.today().isoformat()
            done_tasks = [t for t in done_tasks if (t.get("done_at") or "").startswith(today)]
        elif period == "week":
            cutoff = (_date_type.today() - timedelta(days=7)).isoformat()
            done_tasks = [t for t in done_tasks if (t.get("done_at") or "") >= cutoff]

        if not done_tasks:
            click.echo("No completed tasks in this period.")
            return

        click.echo(f"Completed ({len(done_tasks)})")
        for t in done_tasks:
            done_at = (t.get("done_at") or "")[:10]
            click.echo(f"  {t.get('display_id', ''):<35} {done_at}  {t.get('title', '')}")
    finally:
        conn.close()


@cli.group()
def config():
    """Manage configuration."""
    pass


@config.command("get")
@click.argument("key", required=False)
def config_get(key):
    """Get one or all config values."""
    conn = _open_conn()
    try:
        if key:
            value = core.get_config(conn, key)
            click.echo(f"{key} = {value if value is not None else '(not set)'}")
        else:
            all_cfg = core.get_all_config(conn)
            for k, v in sorted(all_cfg.items()):
                click.echo(f"{k} = {v if v is not None else '(not set)'}")
    finally:
        conn.close()


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a config value."""
    conn = _open_conn()
    try:
        core.set_config(conn, key, value)
        click.echo(f"Set {key} = {value}")
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/cli.py tests/test_cli.py
git commit -m "feat: CLI setup, tasks, history, and config commands"
```

---

## Task 4: CLI — Action Commands + cli_dump helper

**Files:**
- Modify: `src/timeopt/cli.py`
- Modify: `src/timeopt/core.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:
```python
def test_done_marks_task(runner, cli_env):
    from timeopt.cli import cli
    _seed(cli_env, {"title": "fix login bug", "raw": "fix login bug",
                    "priority": "high", "urgent": False, "category": "work", "effort": "medium"})
    result = runner.invoke(cli, ["done", "fix login"])
    assert result.exit_code == 0
    assert "✓" in result.output
    conn = db.get_connection(cli_env)
    row = conn.execute("SELECT status FROM tasks").fetchone()
    conn.close()
    assert row[0] == "done"


def test_done_ambiguous_prompts_user(runner, cli_env):
    from timeopt.cli import cli
    _seed(cli_env,
        {"title": "fix login bug", "raw": "fix login bug",
         "priority": "high", "urgent": False, "category": "work", "effort": "medium"},
        {"title": "fix login redirect", "raw": "fix login redirect",
         "priority": "high", "urgent": False, "category": "work", "effort": "small"},
    )
    conn = db.get_connection(cli_env)
    core.set_config(conn, "fuzzy_match_ask_gap", "100")  # force ambiguity
    conn.close()
    result = runner.invoke(cli, ["done", "login"], input="0\n")  # user skips
    assert result.exit_code == 0


def test_done_no_match(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["done", "xyzzy nonexistent task qqqq"])
    assert result.exit_code == 0
    assert "No confident match" in result.output


def test_dump_with_mocked_llm(runner, cli_env):
    from timeopt.cli import cli
    mock_llm = MagicMock()
    mock_llm.complete.return_value = (
        '[{"raw": "fix login", "title": "fix login", "priority": "high",'
        ' "urgent": false, "category": "work", "effort": "medium"}]'
    )
    with patch("timeopt.cli._get_llm_client", return_value=mock_llm):
        result = runner.invoke(cli, ["dump", "fix login bug"])
    assert result.exit_code == 0
    assert "Added" in result.output
    assert "#1-fix-login" in result.output


def test_check_urgent_no_q3(runner, cli_env):
    from timeopt.cli import cli
    _seed(cli_env, {"title": "important project", "raw": "important",
                    "priority": "high", "urgent": False,
                    "category": "work", "effort": "large"})
    result = runner.invoke(cli, ["check-urgent"])
    assert result.exit_code == 0
    assert "No Q3" in result.output or "All clear" in result.output


def test_check_urgent_shows_q3(runner, cli_env):
    from timeopt.cli import cli
    _seed(cli_env, {"title": "reply to accountant", "raw": "reply to accountant",
                    "priority": "low", "urgent": True,
                    "category": "work", "effort": "small"})
    result = runner.invoke(cli, ["check-urgent"])
    assert result.exit_code == 0
    assert "Q3" in result.output


def test_sync_no_caldav(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["sync"])
    assert result.exit_code == 0
    assert "CalDAV not configured" in result.output


def test_plan_no_tasks(runner, cli_env):
    from timeopt.cli import cli
    result = runner.invoke(cli, ["plan", "--date", "2026-03-28"])
    assert result.exit_code == 0
    assert "No tasks" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_cli.py::test_done_marks_task -v
```

Expected: `AttributeError: cli has no such command 'done'`

- [ ] **Step 3: Add `cli_dump` and `_parse_json_array` to `core.py`**

Append to `src/timeopt/core.py`:
```python
import json as _json
import re as _re


def _parse_json_array(text: str) -> list:
    """Extract a JSON array from LLM response text (strips markdown/preamble)."""
    match = _re.search(r'\[[\s\S]*\]', text)
    if not match:
        raise ValueError(f"LLM response contained no JSON array: {text[:200]}")
    return _json.loads(match.group())


def cli_dump(conn: sqlite3.Connection, llm_client, raw_text: str) -> dict:
    """
    CLI brain dump: split raw text, get templates, fill via LLM, save.
    Returns {count, display_ids}.
    """
    fragments = [f.strip() for f in _re.split(r'[,;]|(?<!\w)and(?!\w)', raw_text)
                 if f.strip()]
    templates_result = get_dump_templates(fragments, events=[])

    system = (
        "You are a task parser. Fill every '?' in each template using context from the task "
        "description. Return ONLY a valid JSON array — no markdown, no explanation. "
        "Valid values are in the schema. Omit optional fields (due_at, due_event_label, "
        "due_event_offset_min) unless the task clearly implies them."
    )
    user = (
        f"Schema: {_json.dumps(templates_result['schema'])}\n\n"
        f"Templates:\n{_json.dumps(templates_result['templates'], indent=2)}"
    )

    raw_response = llm_client.complete(system=system, user=user)
    filled = _parse_json_array(raw_response)

    task_inputs = [
        TaskInput(
            title=t.get("title", ""),
            raw=t.get("raw") or t.get("title", ""),
            priority=t.get("priority", "medium"),
            urgent=bool(t.get("urgent", False)),
            category=t.get("category", "other"),
            effort=t.get("effort") or None,
            due_at=t.get("due_at"),
            due_event_label=t.get("due_event_label"),
            due_event_offset_min=t.get("due_event_offset_min"),
        )
        for t in filled
    ]
    display_ids = dump_tasks(conn, task_inputs)
    logger.info("cli_dump: saved %d tasks", len(display_ids))
    return {"count": len(display_ids), "display_ids": display_ids}
```

- [ ] **Step 4: Append action commands to `cli.py`**

Append to `src/timeopt/cli.py`:
```python
@cli.command()
@click.argument("queries", nargs=-1, required=True)
def done(queries):
    """Mark tasks as done by fuzzy match. Accepts partial names."""
    conn = _open_conn()
    try:
        min_score = int(core.get_config(conn, "fuzzy_match_min_score") or 80)
        ask_gap = int(core.get_config(conn, "fuzzy_match_ask_gap") or 10)

        task_ids = []
        confirmed_dids = []

        for query in queries:
            result = core.fuzzy_match_tasks(conn, query)
            candidates = result.get("candidates", [])

            if not candidates or candidates[0]["score"] < min_score:
                click.echo(f"No confident match for '{query}'.")
                if candidates:
                    click.echo("  Closest:")
                    for c in candidates[:3]:
                        click.echo(f"    {c['display_id']} (score: {c['score']:.0f})")
                continue

            top = candidates[0]
            second_score = candidates[1]["score"] if len(candidates) > 1 else 0

            if len(candidates) >= 2 and (top["score"] - second_score) < ask_gap:
                click.echo(f"Ambiguous match for '{query}':")
                for i, c in enumerate(candidates[:3], 1):
                    click.echo(f"  {i}. {c['display_id']} — {c['title']} (score: {c['score']:.0f})")
                choice = click.prompt("Pick number (0 to skip)", type=int, default=0)
                if choice == 0:
                    continue
                if 1 <= choice <= min(3, len(candidates)):
                    task_ids.append(candidates[choice - 1]["task_id"])
                    confirmed_dids.append(candidates[choice - 1]["display_id"])
            else:
                task_ids.append(top["task_id"])
                confirmed_dids.append(top["display_id"])

        if task_ids:
            core.mark_done(conn, task_ids)
            click.echo("Done:")
            for did in confirmed_dids:
                click.echo(f"  ✓ {did}")
    finally:
        conn.close()


@cli.command()
@click.argument("text")
def dump(text):
    """Brain-dump tasks in free-form text. Parses with LLM and saves."""
    conn = _open_conn()
    try:
        llm = _get_llm_client(conn)
        result = core.cli_dump(conn, llm, text)
        click.echo(f"Added {result['count']} task(s):")
        for did in result["display_ids"]:
            click.echo(f"  {did}")
    finally:
        conn.close()


@cli.command()
@click.option("--date", "plan_date", default=None,
              help="Date to plan for (YYYY-MM-DD, default today)")
def plan(plan_date):
    """Generate and push a daily task schedule."""
    conn = _open_conn()
    try:
        caldav = _get_caldav_client(conn)
        if not caldav:
            click.echo("Warning: CalDAV not configured — planning without calendar data.", err=True)

        target = plan_date or _date_type.today().isoformat()
        events = []
        if caldav:
            try:
                events = caldav.get_events(target, days=1)
            except Exception:
                logger.exception("plan: CalDAV unavailable, proceeding without calendar")

        proposal = planner.get_plan_proposal(conn, events, target)
        blocks = proposal.get("blocks", [])

        if not blocks:
            click.echo("No tasks to schedule.")
            return

        click.echo("Proposed schedule:")
        from datetime import datetime as _dt, timedelta as _td
        for b in blocks:
            start_str = b.get("start", "")
            if len(start_str) >= 16:
                start_dt = _dt.fromisoformat(start_str)
                end_dt = start_dt + _td(minutes=b.get("duration_min", 0))
                click.echo(
                    f"  {start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"
                    f"  {b.get('display_id', ''):<35} [{b.get('quadrant', '')}]"
                )

        deferred = proposal.get("deferred", [])
        if deferred:
            click.echo(f"\nDeferred ({len(deferred)}):")
            for d in deferred:
                click.echo(f"  {d.get('display_id', '')} — {d.get('title', '')}")

        if not caldav:
            click.echo("\nCalDAV not configured — skipping calendar push.")
            return

        if not click.confirm("\nPush to calendar?", default=True):
            return

        planner.push_calendar_blocks(conn, proposal, target, caldav)
        click.echo(f"Pushed {len(blocks)} block(s) to calendar.")
    finally:
        conn.close()


@cli.command("check-urgent")
def check_urgent():
    """Classify tasks and show Q3 (urgent, not important) tasks for delegation."""
    conn = _open_conn()
    try:
        result = planner.classify_tasks(conn)
        q3_tasks = [t for t in result.get("tasks", [])
                    if t.get("quadrant") == "Q3" and t.get("status") == "pending"]

        if not q3_tasks:
            click.echo("No Q3 tasks. All clear.")
            return

        click.echo(f"Q3 tasks (urgent + not important) — {len(q3_tasks)} found:")
        for t in q3_tasks:
            click.echo(f"  {t.get('display_id', ''):<35} {t.get('title', '')}")
        click.echo("\nTip: Run '/check-urgent' in Claude Code to automatically delegate these.")
    finally:
        conn.close()


@cli.command()
def sync():
    """Sync due dates for tasks bound to calendar events."""
    conn = _open_conn()
    try:
        caldav = _get_caldav_client(conn)
        if not caldav:
            click.echo("CalDAV not configured. Set caldav_username and caldav_password.")
            return

        try:
            events = caldav.get_events(_date_type.today().isoformat(), days=90)
        except Exception as e:
            click.echo(f"CalDAV error: {e}", err=True)
            return

        changes = core.sync_bound_tasks(conn, events)
        resolved = core.try_resolve_unresolved(conn, events)
        still_unresolved = core.get_unresolved_tasks(conn)

        if changes:
            click.echo(f"Updated {len(changes)} task due date(s):")
            for c in changes:
                if c["status"] == "updated":
                    old = (c["old_due_at"] or "")[:10]
                    new = (c["new_due_at"] or "")[:10]
                    click.echo(f"  {c['display_id']}  {old} → {new}")
                elif c["status"] == "event_missing":
                    click.echo(f"  {c['display_id']}  ⚠ bound event deleted — due date preserved")
        else:
            click.echo("No due date changes.")

        newly_resolved = [r for r in resolved if r["status"] == "resolved"]
        if newly_resolved:
            click.echo(f"\nResolved {len(newly_resolved)} previously unresolved task(s).")

        if still_unresolved:
            click.echo(f"\n{len(still_unresolved)} task(s) still have unresolved calendar references:")
            for t in still_unresolved:
                click.echo(f"  {t['display_id']}  ref: {t.get('due_event_label', '?')}")
            click.echo("Run '/sync' in Claude Code to resolve these interactively.")
    finally:
        conn.close()
```

- [ ] **Step 5: Run all CLI tests to verify they pass**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: 17 passed.

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/timeopt/cli.py src/timeopt/core.py tests/test_cli.py
git commit -m "feat: CLI action commands (done, dump, plan, check-urgent, sync) + cli_dump helper"
```

---

## Task 5: Slash Commands

**Files:**
- Create: `.claude/commands/dump.md`
- Create: `.claude/commands/tasks.md`
- Create: `.claude/commands/plan.md`
- Create: `.claude/commands/done.md`
- Create: `.claude/commands/check-urgent.md`
- Create: `.claude/commands/sync.md`
- Create: `.claude/commands/history.md`

- [ ] **Step 1: Create the commands directory**

```bash
mkdir -p .claude/commands
```

- [ ] **Step 2: Write `.claude/commands/dump.md`**

```markdown
**Task:** Process the user's brain dump and save tasks to timeopt.

**Input:** $ARGUMENTS

**Steps:**

1. **Split** — identify task fragments. Separate on commas, semicolons, newlines, "and also", "and then". Keep urgency markers and time references with their fragment.

2. **Get templates** — call `get_dump_templates` with the fragment list.

3. **Fill templates** — for each template returned, infer and fill all `"?"` fields:
   - `priority`: `"high"` for critical/deadline tasks; `"medium"` default; `"low"` for nice-to-haves
   - `urgent`: `true` if text contains "urgent", "ASAP", "before noon", "today", or has an imminent due date
   - `category`: `"work"`, `"personal"`, `"errands"`, or `"other"` from context
   - `effort`: `"small"` (≤30min), `"medium"` (~1hr), `"large"` (>1.5hr) from complexity
   - `due_at`: ISO8601 UTC if a specific time is mentioned (e.g. "before noon" → today `12:00:00Z`)
   - `due_event_offset_min`: negative int = minutes before a calendar event (e.g. `-30`)
   - Omit optional fields already absent from the template

4. **Save** — call `dump_tasks(tasks: [...])` with all filled templates as a batch.

5. **Confirm** — show what was saved:
   ```
   Added N tasks:
     #1-fix-login-bug             [work, high]
     #3-deploy-hotfix-before-noon [work, high, urgent, due today 12:00]
   ```

**Defaults:** effort unclear → call `get_config(key="default_effort")`. Category unclear → best guess, no confirmation needed.
```

- [ ] **Step 3: Write `.claude/commands/tasks.md`**

```markdown
**Task:** Show the user's current tasks from timeopt.

Call `list_tasks()`. If $ARGUMENTS contains filters (e.g. `--done`, `--priority high`, `--category work`), pass them as parameters.

Format the output:
```
Pending (N)
  #1-display-id          [category, priority]
  #2-display-id          [category, priority, urgent, due YYYY-MM-DD]
  ...

Being handled by Claude (N)
  #X-display-id          [category, priority — last note preview]
  ...
```

Tasks appear in Eisenhower order: Q1 (urgent+important) → Q2 (important) → Q3 (urgent) → Q4 (neither). Show the last line of `notes` for delegated tasks (truncated to 60 chars).
```

- [ ] **Step 4: Write `.claude/commands/plan.md`**

```markdown
**Task:** Generate and push a daily task schedule.

1. Call `get_plan_proposal(date?)`. The server computes the full schedule — free slots, Eisenhower sort, effort mapping, breaks, overflow deferral. No scheduling reasoning needed.

2. Display the proposal:
   ```
   Proposed schedule for [date]:
     10:00–11:00  #1-fix-login-bug    [Q2, medium]
     11:15–12:15  #3-deploy-hotfix    [Q1, medium]
     ...
   Deferred: #5-low-priority (not enough time today)
   ```

3. Confirm with the user: "Push this to your calendar?"

4. On confirmation: call `push_calendar_blocks(blocks: [...], date: "YYYY-MM-DD")` with the `blocks` array from the proposal.

5. Report success: "Pushed N blocks to Timeopt calendar."

If CalDAV is not configured, display the schedule but skip the push step and explain.

Input (optional date): $ARGUMENTS
```

- [ ] **Step 5: Write `.claude/commands/done.md`**

```markdown
**Task:** Mark tasks as done in timeopt.

**Input:** $ARGUMENTS (partial task names or IDs, space-separated)

For each word/phrase in the input:

1. Call `fuzzy_match_tasks(query: "<phrase>")`.

2. **Ambiguity rules** (get thresholds with `get_config()`):
   - Score < `fuzzy_match_min_score` (default 80): ask which task was meant
   - Gap between top two scores < `fuzzy_match_ask_gap` (default 10): ask to confirm
   - Otherwise: act silently

3. Call `mark_done(task_ids: ["<uuid>", ...])` with all confirmed IDs.

4. Confirm:
   ```
   Done:
     ✓ #1-fix-login-bug
     ✓ #4-prep-slides
   ```
```

- [ ] **Step 6: Write `.claude/commands/check-urgent.md`**

```markdown
**Task:** Check for urgent tasks that can be delegated to Claude, then delegate them.

1. Call `classify_tasks()` to run Eisenhower classification.

2. Find Q3 tasks: `urgent=true` AND `priority="low"` AND `status="pending"`.

3. For each Q3 task:
   a. Call `mark_delegated(task_id: "<id>", notes: "Starting delegation")`.
   b. Create a TodoWrite entry: "Delegate: [task title]".
   c. Attempt the task using available tools. Budget: check `get_config(key="delegation_max_tool_calls")`.
   d. Progress: call `update_task_notes(task_id: "<id>", notes: "<progress>")` as you work.
   e. On success: call `mark_done(task_ids: ["<id>"])` + final `update_task_notes` with summary.
   f. On failure or budget exceeded: call `return_to_pending(task_id: "<id>", notes: "<reason>")`.

4. Report:
   ```
   Delegated 1 task:
     #6-reply-to-accountant → handled successfully

   Could not delegate:
     #7-book-flight → returned to queue (no booking tool available)
   ```

If no Q3 tasks: "No urgent tasks to delegate. All clear."
```

- [ ] **Step 7: Write `.claude/commands/sync.md`**

```markdown
**Task:** Sync calendar event bindings for timeopt tasks.

1. Call `sync_calendar()`. This runs both sync phases server-side:
   - Algorithmic: updates `due_at` for tasks bound to moved events
   - Re-binding: attempts to match previously unresolved calendar references

2. Display results:
   ```
   Updated 2 task due dates:
     #5-prep-report    Wed 14:00 → Thu 10:00
     #8-send-invoice   Wed 14:00 → Thu 10:00

   Resolved 1 previously unresolved task:
     #9-board-prep → bound to "Board Meeting" Apr 15
   ```

3. For tasks in `unresolved_remaining`: try to estimate a `due_at` from the task title and world knowledge. If you cannot estimate, ask: "When do you expect '[event name]'?" — they can give a date or say Skip. Use `set_config` is not needed here; just call `mark_done` or update notes as appropriate.

If CalDAV is not configured, explain setup: `timeopt config set caldav_username <user>` etc.
```

- [ ] **Step 8: Write `.claude/commands/history.md`**

```markdown
**Task:** Show completed tasks from timeopt.

Call `list_tasks(status: "done", include_old_done: true)`.

If $ARGUMENTS contains:
- `--today`: filter to tasks with `done_at` matching today's date
- `--week`: filter to tasks completed in the last 7 days
- `--all` or empty: show all completed tasks

Display:
```
Completed (N)
  #1-fix-login-bug    2026-03-27  fix login bug
  #4-prep-slides      2026-03-26  prep slides for Thursday
```

Most recently completed first.
```

- [ ] **Step 9: Commit**

```bash
git add .claude/commands/
git commit -m "feat: slash command prompt templates for all timeopt commands"
```

---

## Task 6: Plugin Configuration Files

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `.mcp.json`

- [ ] **Step 1: Create `.claude-plugin/plugin.json`**

```bash
mkdir -p .claude-plugin
```

`.claude-plugin/plugin.json`:
```json
{
  "name": "timeopt",
  "display_name": "Timeopt",
  "description": "Personal task manager with Eisenhower Matrix prioritization and Yandex Calendar integration. Brain-dump tasks, generate a daily schedule, and delegate urgent tasks to Claude.",
  "version": "0.1.0",
  "mcp_server": "timeopt",
  "commands": ["dump", "tasks", "plan", "done", "check-urgent", "sync", "history"]
}
```

- [ ] **Step 2: Create `.mcp.json`**

`.mcp.json`:
```json
{
  "mcpServers": {
    "timeopt": {
      "command": "uv",
      "args": ["run", "--directory", "${CLAUDE_PLUGIN_ROOT}", "timeopt-server"]
    }
  }
}
```

- [ ] **Step 3: Run full test suite to confirm everything still passes**

```bash
uv run pytest -v
```

Expected: all pass.

- [ ] **Step 4: Smoke-test the server entry point**

```bash
uv run timeopt --help
```

Expected: shows timeopt CLI help with all subcommands listed.

- [ ] **Step 5: Commit**

```bash
git add .claude-plugin/plugin.json .mcp.json
git commit -m "feat: plugin.json and .mcp.json — Claude Code integration complete"
```

---

## Self-Review

**Spec coverage:**
- All 16 MCP tools from spec: ✅ (`list_tasks`, `get_task`, `fuzzy_match_tasks`, `mark_done`, `mark_delegated`, `update_task_notes`, `return_to_pending`, `resolve_calendar_reference`, `get_calendar_events`, `get_plan_proposal`, `push_calendar_blocks`, `classify_tasks`, `get_config`, `set_config`, `get_dump_templates`, `dump_task`/`dump_tasks`) + `sync_calendar`
- All 8 CLI commands: ✅ (`tasks`, `done`, `dump`, `plan`, `check-urgent`, `sync`, `history`, `config`)
- All 7 slash commands: ✅
- Plugin files: ✅
- CalDAV not configured → graceful warning (not crash): ✅ (every CalDAV tool returns `{"error": "..."}` or warns)
- Delegation flow in `/check-urgent.md`: ✅
- Transactional `push_calendar_blocks` wrapping in server: ✅ (`{"blocks": blocks}` wrapper)
- `cli_dump` uses `get_dump_templates` → LLM fill → `dump_tasks`: ✅

**No placeholders:** all steps have complete code or exact commands. ✅

**Type consistency:**
- `push_calendar_blocks(conn, proposal, date, caldav_client)` — server wraps `blocks` list as `{"blocks": blocks}` before passing. ✅
- `get_plan_proposal(conn, events, date)` — server fetches events from CalDAV first. ✅
- `get_dump_templates(fragments, events)` — server fetches 30-day events from CalDAV. ✅
- `dump_task(conn, TaskInput)` returns `str` (display_id) — server queries for `id` separately. ✅
