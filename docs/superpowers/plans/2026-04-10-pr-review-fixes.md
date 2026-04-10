# PR Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all critical and important issues identified in the PR review of `feat/config-setup-ui`, following TDD.

**Architecture:** Bug fixes across `cli.py`, `server.py`, `caldav_client.py`, `ui_server.py`, and documentation files. Each fix is tested first.

**Tech Stack:** Python, pytest, FastAPI, click, SQLite

---

## Issue Summary

From the PR review, the following issues were identified (in priority order):

### Critical
1. **CLI sync crashes** — `cli.py:439-444` passes dicts to `core.sync_bound_tasks` instead of `CalendarEvent` objects
2. **Unhandled ValueError** — `server.py:276` `int()` cast on config value with no try/except
3. **SRI hash** — Verify `templates/base.html` HTMX SRI hash is correct

### Important
4. **set_config return shape** — `server.py:210-214` returns `{"error": ...}` not `{"ok": False, "error": ...}`, no logging
5. **Sensitive echo** — `cli.py:195` echoes API keys to stdout on `config set`
6. **Dead try/except** — `server.py:364-368` wraps `get_events` which never raises
7. **uvicorn error handling** — `cli.py:495-500` raw tracebacks on port-in-use
8. **Log level** — `caldav_client.py:69-71` uses `logger.error` for handled degradation (should be `warning`)
9. **Missing logging** — `ui_server.py:77-81` KeyError path not logged; `caldav_client.py:133-136` UID fallback not logged

### Documentation
10. **Doc fixes** — `tests/CLAUDE.md` tool count wrong (19→18), optional config list wrong, slash commands missing `/timeopt:setup`, test file table incomplete

---

## Task 1: Fix CLI sync CalendarEvent dict conversion + add failing test

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/timeopt/cli.py:439-444`

- [ ] **Step 1: Write the failing test**

```python
def test_cli_sync_updates_task_with_due_event_uid(runner, cli_env):
    """sync correctly updates due date for task bound by UID (not just label)."""
    from timeopt.caldav_client import CalendarEvent
    conn = db.get_connection(cli_env)
    task_id = core.dump_task(conn, core.TaskInput(
        title="bound task", raw="bound task", priority="high", urgent=False,
        category="work", effort="small"
    ))
    conn.execute("UPDATE tasks SET due_event_uid='e-uid-1' WHERE id=?", (task_id,))
    conn.commit()
    conn.close()

    event = CalendarEvent(
        start="2026-04-20T10:00:00Z", end="2026-04-20T11:00:00Z",
        title="The Meeting", uid="e-uid-1"
    )
    mock_caldav = MagicMock()
    mock_caldav.get_events.return_value = [event]
    with patch("timeopt.cli._get_caldav_client", return_value=mock_caldav):
        result = runner.invoke(cli, ["sync"])
    assert result.exit_code == 0, f"sync crashed: {result.output}\n{result.exception}"
    assert "Updated" in result.output or "No due date changes" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_cli_sync_updates_task_with_due_event_uid -v`
Expected: FAIL with `AttributeError: 'dict' object has no attribute 'uid'`

- [ ] **Step 3: Fix cli.py sync command**

In `cli.py`, the `sync` command (around line 439), replace:
```python
events_raw = caldav.get_events(_date_type.today().isoformat(), days=90)
events = [{"start": e.start, "end": e.end, "title": e.title} for e in events_raw]
...
changes = core.sync_bound_tasks(conn, events)
resolved = core.try_resolve_unresolved(conn, events)
```
with:
```python
events_raw = caldav.get_events(_date_type.today().isoformat(), days=90)
changes = core.sync_bound_tasks(conn, events_raw)
resolved = core.try_resolve_unresolved(conn, events_raw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_cli_sync_updates_task_with_due_event_uid -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -q --tb=short`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add tests/test_cli.py src/timeopt/cli.py
git commit -m "fix(cli): pass CalendarEvent objects directly to sync — remove dict conversion"
```

---

## Task 2: Fix resolve_calendar_reference unhandled ValueError + add test

**Files:**
- Modify: `tests/test_server.py`
- Modify: `src/timeopt/server.py:276`

- [ ] **Step 1: Write the failing test**

```python
def test_resolve_calendar_reference_bad_min_score_config(server_env):
    """Corrupt calendar_fuzzy_min_score config does not crash resolve_calendar_reference."""
    from timeopt import server
    conn = db.get_connection(server_env)
    core.set_config(conn, "calendar_fuzzy_min_score", "not_a_number")
    conn.commit()
    conn.close()

    result = server.resolve_calendar_reference.__wrapped__(
        label="standup", date_range=7
    ) if hasattr(server.resolve_calendar_reference, "__wrapped__") else None

    # Call via the actual MCP tool function
    from timeopt.server import app as mcp_app
    # Direct call — invoke the underlying function
    import asyncio
    from timeopt import server as srv
    # Find the function
    result = asyncio.run(srv.resolve_calendar_reference(label="standup", date_range=7))
    assert "error" not in result or result.get("candidates") is not None
    assert result.get("candidates") is not None  # Should return empty list, not crash
```

Actually, the server tools in this project are MCP tools using `@mcp.tool()`. Let me write a more targeted test:

```python
def test_resolve_calendar_reference_handles_bad_min_score_config(server_env):
    """Corrupt calendar_fuzzy_min_score in DB falls back to default instead of crashing."""
    conn = db.get_connection(server_env)
    # Directly write a non-integer value for the config key
    conn.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
        ("calendar_fuzzy_min_score", "not_a_number")
    )
    conn.commit()
    conn.close()

    # The server tool reads from TIMEOPT_DB — verify via get_config that it's set
    conn2 = db.get_connection(server_env)
    assert core.get_config(conn2, "calendar_fuzzy_min_score") == "not_a_number"
    conn2.close()

    # Import and call the underlying server tool handler
    # Server tools wrap their logic in the decorated function
    # We test via the server module directly
    import importlib
    import timeopt.server as srv_mod
    importlib.reload(srv_mod)  # ensure fresh env read
    # Calling the MCP tool directly
    import asyncio
    try:
        result = asyncio.run(srv_mod.resolve_calendar_reference(label="standup", date_range=7))
        # Should not raise — should fall back to default score 50
        assert "candidates" in result
    except ValueError as e:
        pytest.fail(f"ValueError not caught: {e}")
```

For simplicity given the MCP tool calling pattern, use the same `patch` pattern as other server tests:

```python
def test_resolve_calendar_reference_bad_min_score_uses_default(server_env):
    """Non-integer calendar_fuzzy_min_score falls back to 50 instead of raising."""
    conn = db.get_connection(server_env)
    conn.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
        ("calendar_fuzzy_min_score", "bad_value")
    )
    conn.commit()
    conn.close()

    # Patch CalDAV to return empty (CalDAV not relevant here — test is config parsing)
    with patch("timeopt.server._get_caldav", return_value=None):
        result = asyncio.run(resolve_calendar_reference_tool(label="standup", date_range=7))
    # Should return candidates list (empty), not crash with ValueError
    assert "candidates" in result
    assert isinstance(result["candidates"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_resolve_calendar_reference_bad_min_score_uses_default -v`
Expected: FAIL with `ValueError: invalid literal for int() with base 10: 'bad_value'`

- [ ] **Step 3: Fix server.py**

In `server.py` around line 276, replace:
```python
min_score = int(core.get_config(conn, "calendar_fuzzy_min_score"))
```
with:
```python
try:
    min_score = int(core.get_config(conn, "calendar_fuzzy_min_score"))
except ValueError:
    logger.warning(
        "resolve_calendar_reference: calendar_fuzzy_min_score is not an integer, using default 50"
    )
    min_score = 50
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_server.py::test_resolve_calendar_reference_bad_min_score_uses_default -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -q --tb=short`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add tests/test_server.py src/timeopt/server.py
git commit -m "fix(server): guard int() cast on calendar_fuzzy_min_score config with fallback to 50"
```

---

## Task 3: Fix set_config return shape + add logging + add test

**Files:**
- Modify: `tests/test_server.py`
- Modify: `src/timeopt/server.py:210-214`

- [ ] **Step 1: Write the failing test**

```python
def test_set_config_unknown_key_returns_ok_false(server_env):
    """set_config with unknown key returns {ok: False, error: ...} not just {error: ...}."""
    result = asyncio.run(set_config_tool(key="nonexistent_key_xyz", value="foo"))
    assert result.get("ok") is False
    assert "error" in result
    assert "nonexistent_key_xyz" in result["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_set_config_unknown_key_returns_ok_false -v`
Expected: FAIL (result has no "ok" key)

- [ ] **Step 3: Fix server.py set_config**

In `server.py`, find the `set_config` tool handler. Change the `KeyError` except block from:
```python
except KeyError as e:
    return {"error": str(e)}
```
to:
```python
except KeyError as e:
    logger.warning("set_config: rejected unknown key=%s", key)
    return {"ok": False, "error": str(e)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_server.py::test_set_config_unknown_key_returns_ok_false -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -q --tb=short`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add tests/test_server.py src/timeopt/server.py
git commit -m "fix(server): normalize set_config error return to {ok: False, error: ...} + add logging"
```

---

## Task 4: Fix sensitive value echo in config_set CLI + add test

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/timeopt/cli.py:195`

- [ ] **Step 1: Write the failing test**

```python
def test_config_set_sensitive_key_does_not_echo_value(runner, cli_env):
    """config set llm_api_key does not print the actual key value."""
    result = runner.invoke(cli, ["config-set", "llm_api_key", "sk-secret-abc123"])
    assert result.exit_code == 0
    assert "sk-secret-abc123" not in result.output
    assert "llm_api_key" in result.output  # Key name is fine to show
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_config_set_sensitive_key_does_not_echo_value -v`
Expected: FAIL (secret value appears in output)

- [ ] **Step 3: Fix cli.py config_set**

In `cli.py`, find the `config_set` command. After the `core.set_config` call, replace:
```python
click.echo(f"Set {key} = {value}")
```
with:
```python
display_value = "***" if key in core._SENSITIVE_CONFIG_KEYS else value
click.echo(f"Set {key} = {display_value}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_config_set_sensitive_key_does_not_echo_value -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -q --tb=short`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add tests/test_cli.py src/timeopt/cli.py
git commit -m "fix(cli): mask sensitive config values (llm_api_key, caldav_password) in config-set output"
```

---

## Task 5: Remove dead try/except in sync_calendar + fix log level in caldav_client

**Files:**
- Modify: `src/timeopt/server.py:364-368`
- Modify: `src/timeopt/caldav_client.py:69-71`

No new tests needed for these (existing tests cover the behavior; this is a cleanup/correctness fix).

- [ ] **Step 1: Remove dead try/except in server.py sync_calendar**

In `server.py`, find the `sync_calendar` tool. Remove the dead `try/except` wrapper around `get_events`:

Replace:
```python
try:
    events_raw = caldav.get_events(_date_type.today().isoformat(), days=date_range_days)
except Exception:
    logger.exception("sync_calendar: CalDAV get_events failed")
    return {"ok": False, "error": "CalDAV unavailable during sync"}
```
with:
```python
events_raw = caldav.get_events(_date_type.today().isoformat(), days=date_range_days)
```

Add a comment above: `# get_events never raises — degrades to [] internally on failure`

- [ ] **Step 2: Fix log level in caldav_client.py**

In `caldav_client.py`, find the `get_events` method. Change:
```python
logger.error("get_events: caldav package is not installed — returning empty list")
```
to:
```python
logger.warning("get_events: caldav package is not installed — returning empty list")
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -q --tb=short`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add src/timeopt/server.py src/timeopt/caldav_client.py
git commit -m "fix: remove dead try/except around get_events in sync_calendar; fix log level to warning"
```

---

## Task 6: Add logging for missing silent failures

**Files:**
- Modify: `src/timeopt/ui_server.py:77-81`
- Modify: `src/timeopt/caldav_client.py:133-136`
- Modify: `tests/test_ui_server.py`
- Modify: `tests/test_caldav.py`

- [ ] **Step 1: Write failing test for ui_server.py KeyError logging**

```python
def test_post_config_unknown_key_is_logged(client, caplog):
    """POST /api/config/{key} with unknown key logs a warning."""
    import logging
    with caplog.at_level(logging.WARNING, logger="timeopt.ui_server"):
        response = client.post("/api/config/totally_unknown_key_xyz", data={"value": "foo"})
    assert response.status_code == 200
    assert any("totally_unknown_key_xyz" in r.message for r in caplog.records)
```

- [ ] **Step 2: Write failing test for caldav_client.py UID fallback logging**

```python
def test_create_event_logs_warning_when_uid_extraction_fails(mock_caldav_lib):
    """create_event logs a warning when server UID extraction fails."""
    import logging
    # Make event.instance.vevent.uid.value raise AttributeError
    mock_event = MagicMock()
    mock_event.instance.vevent.uid.value  # This will work by default with MagicMock
    # Force the UID attribute to raise
    type(mock_event.instance.vevent.uid).value = PropertyMock(side_effect=AttributeError("no uid"))
    mock_caldav_lib.return_value.get_events.return_value = []  # not used
    # Set up principal/calendar chain
    # ... (use existing test fixture pattern from test_caldav.py)
    client = CalDAVClient(url="https://example.com", username="u", password="p")
    # Patch the calendar.save_event to return our mock_event
    with patch.object(client._client.principal().calendars()[0], 'save_event', return_value=mock_event):
        with caplog.at_level(logging.WARNING, logger="timeopt.caldav_client"):
            uid = client.create_event(...)
    assert any("could not read server UID" in r.message for r in caplog.records)
    assert uid is not None  # Still returns the generated UID
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_ui_server.py::test_post_config_unknown_key_is_logged tests/test_caldav.py::test_create_event_logs_warning_when_uid_extraction_fails -v`
Expected: FAIL

- [ ] **Step 4: Fix ui_server.py — add logging on KeyError**

In `ui_server.py`, find the `set_config_field` endpoint's `except KeyError as e:` block. Add logging:
```python
except KeyError as e:
    logger.warning("set_config_field: unknown config key submitted: %s", key)
    return templates.TemplateResponse(
        request, "partials/config_field.html",
        {"key": key, "value": value, "status": "error", "error": str(e)},
    )
```

- [ ] **Step 5: Fix caldav_client.py — add warning on UID extraction fallback**

In `caldav_client.py`, find the inner `except Exception:` block that falls back to the local `uid`:
```python
try:
    server_uid = event.instance.vevent.uid.value
except Exception:
    server_uid = uid
```
Change to:
```python
try:
    server_uid = event.instance.vevent.uid.value
except Exception:
    logger.warning(
        "create_event: could not read server UID for '%s', using generated uid=%s",
        title, uid
    )
    server_uid = uid
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_ui_server.py::test_post_config_unknown_key_is_logged -v`
Run: `uv run pytest tests/ -q --tb=short`
Expected: all tests pass (caldav UID test may need fixture adjustment)

- [ ] **Step 7: Commit**

```bash
git add tests/test_ui_server.py tests/test_caldav.py src/timeopt/ui_server.py src/timeopt/caldav_client.py
git commit -m "fix: add missing logging for KeyError in ui_server and UID fallback in caldav_client"
```

---

## Task 7: Fix documentation errors

**Files:**
- Modify: `tests/CLAUDE.md`
- Modify: `src/timeopt/CLAUDE.md`
- Modify: `CLAUDE.md`

No tests needed for documentation.

- [ ] **Step 1: Fix tests/CLAUDE.md**

  a. Change "19 server tools" → "18 server tools"
  b. Clarify CalendarEvent/dict conversion: "The server converts to dicts **only** for `planner.get_plan_proposal` (planner expects list[dict]). All other server tools pass CalendarEvent objects directly to core.* functions."
  c. Add missing test files to the "What's Tested Where" table:
     - `test_ui_server.py` — FastAPI config UI endpoints (GET/POST /config, /api/config)
     - `test_integration.py` — cross-module integration scenarios (config→planner, sync lifecycle, delegation)
     - `test_e2e_cli.py` — end-to-end CLI scenarios
     - `test_e2e_server.py` — end-to-end server scenarios

- [ ] **Step 2: Fix src/timeopt/CLAUDE.md**

  a. Fix optional config keys: replace `Optional config keys (caldav_*, llm_*)` with `Optional config keys (caldav_username, caldav_password, llm_base_url, llm_api_key, llm_model)`
  b. Add carve-out to "Do NOT convert to dicts" rule: "Exception: `server.get_plan_proposal` converts events to `list[dict]` for the planner, which expects `{start, end, title}` dicts. All `core.*` functions take raw CalendarEvent objects."

- [ ] **Step 3: Fix root CLAUDE.md**

  Add `/timeopt:setup` to the `## Slash Commands` list.

- [ ] **Step 4: Commit**

```bash
git add tests/CLAUDE.md src/timeopt/CLAUDE.md CLAUDE.md
git commit -m "docs: fix tool count, optional config list, slash commands, and test file table"
```

---

## Task 8: Verify and fix HTMX SRI hash

**Files:**
- Modify: `src/timeopt/templates/base.html` (if hash is wrong)

- [ ] **Step 1: Fetch the actual file and compute the hash**

```bash
curl -s https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js | openssl dgst -sha384 -binary | openssl base64 -A
```

- [ ] **Step 2: Compare with current hash**

Current hash: `sha384-ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2`

- [ ] **Step 3: Update if different**

If hash differs, update `base.html`:
```html
<script src="https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js"
        integrity="sha384-<ACTUAL_HASH>"
        crossorigin="anonymous"></script>
```

- [ ] **Step 4: Commit (only if changed)**

```bash
git add src/timeopt/templates/base.html
git commit -m "fix(templates): update HTMX SRI hash to correct value for 1.9.12"
```

---

## Verification

After all tasks:
1. `uv run pytest tests/ -v --tb=short` — all tests pass
2. `uv run pytest tests/ --cov=timeopt --cov-report=term-missing -q` — coverage ≥ 97%
3. Run PR review skill to confirm no remaining issues
