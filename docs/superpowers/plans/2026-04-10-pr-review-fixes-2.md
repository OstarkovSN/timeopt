# PR Review Fixes Round 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all issues found in the second PR review round: sensitive config leaks in HTML, dead try/except blocks, missing error handling, weak tests.

**Architecture:** TDD first — write failing tests, then fix implementation.

**Tech Stack:** Python, pytest, FastAPI, click, SQLite

---

### Task 1: Fix sensitive config leaks in ui_server HTML rendering

**Files:**
- Modify: `src/timeopt/ui_server.py` (lines 41-58, 73-75)
- Modify: `tests/test_ui_server.py`

**Issue:** `config_page` (line 41) and `config_partial` (line 56) pass raw `cfg` to templates without masking `llm_api_key` / `caldav_password`. `set_config_field` (line 75) returns plaintext value in HTMX response. Also: `str(KeyError)` produces double-quoted string — use `e.args[0]`.

- [ ] **Step 1: Write failing tests**

```python
def test_config_page_does_not_expose_sensitive_values_in_html(ui_env):
    """GET /config must not include raw llm_api_key in HTML source."""
    conn = db.get_connection(ui_env)
    core.set_config(conn, "llm_api_key", "sk-secret-key-12345")
    conn.close()
    from fastapi.testclient import TestClient
    from timeopt.ui_server import app
    client = TestClient(app)
    resp = client.get("/config")
    assert resp.status_code == 200
    assert "sk-secret-key-12345" not in resp.text
    assert "***" in resp.text or 'type="password"' in resp.text


def test_config_partial_does_not_expose_sensitive_values(ui_env):
    """GET /partials/config must not expose llm_api_key in HTML."""
    conn = db.get_connection(ui_env)
    core.set_config(conn, "llm_api_key", "sk-secret-key-partial")
    conn.close()
    from fastapi.testclient import TestClient
    from timeopt.ui_server import app
    client = TestClient(app)
    resp = client.get("/partials/config")
    assert resp.status_code == 200
    assert "sk-secret-key-partial" not in resp.text


def test_post_config_sensitive_key_does_not_echo_value_in_response(ui_env):
    """POST /api/config/llm_api_key must not return the raw key in the HTMX response."""
    from fastapi.testclient import TestClient
    from timeopt.ui_server import app
    client = TestClient(app)
    resp = client.post("/api/config/llm_api_key", data={"value": "sk-plaintext-secret"})
    assert resp.status_code == 200
    assert "sk-plaintext-secret" not in resp.text


def test_post_config_unknown_key_error_message_not_double_quoted(ui_env):
    """POST with unknown key should show clean error, not 'Unknown config key: ...' with extra quotes."""
    from fastapi.testclient import TestClient
    from timeopt.ui_server import app
    client = TestClient(app)
    resp = client.post("/api/config/nonexistent_key", data={"value": "x"})
    assert resp.status_code == 200
    # Should not have double-quotes from str(KeyError)
    assert "\"Unknown config key:" not in resp.text
    assert "'Unknown config key:" not in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_ui_server.py::test_config_page_does_not_expose_sensitive_values_in_html tests/test_ui_server.py::test_config_partial_does_not_expose_sensitive_values tests/test_ui_server.py::test_post_config_sensitive_key_does_not_echo_value_in_response tests/test_ui_server.py::test_post_config_unknown_key_error_message_not_double_quoted -v
```

- [ ] **Step 3: Fix `ui_server.py`**

In `config_page` (line 41), mask sensitive keys before passing to template:
```python
cfg = core.get_all_config(conn)
for k in core._SENSITIVE_CONFIG_KEYS:
    if cfg.get(k):
        cfg[k] = "***"
return templates.TemplateResponse(request, "config.html", {"config": cfg})
```

In `config_partial` (line 56), same masking:
```python
cfg = core.get_all_config(conn)
for k in core._SENSITIVE_CONFIG_KEYS:
    if cfg.get(k):
        cfg[k] = "***"
return templates.TemplateResponse(request, "partials/config.html", {"config": cfg})
```

In `set_config_field` success path (line 73-75), mask value:
```python
display_value = "***" if key in core._SENSITIVE_CONFIG_KEYS else value
return templates.TemplateResponse(
    request, "partials/config_field.html",
    {"key": key, "value": display_value, "status": "saved"},
)
```

For the `KeyError` path (line 81), use `e.args[0]` instead of `str(e)`:
```python
except KeyError as e:
    logger.warning("set_config_field: unknown config key submitted: %s", key)
    error_msg = e.args[0] if e.args else str(e)
    return templates.TemplateResponse(
        request, "partials/config_field.html",
        {"key": key, "value": value, "status": "error", "error": error_msg},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_ui_server.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/ui_server.py tests/test_ui_server.py
git commit -m "fix(ui): mask sensitive config values in HTML rendering and POST response"
```

---

### Task 2: Remove dead try/except blocks around get_events

**Files:**
- Modify: `src/timeopt/cli.py` (lines 456-460)
- Modify: `src/timeopt/server.py` (lines 233-236, 327-330)

**Issue:** `caldav.get_events()` never raises — it handles all exceptions internally. Three locations have dead `try/except Exception` blocks that (a) mislead maintainers and (b) would silently swallow unrelated future errors with wrong log messages.

Note: No new tests needed here since `get_events` never raises. We verify existing tests still pass after removal.

- [ ] **Step 1: Fix `cli.py` sync command (lines 456-460)**

Remove the dead try/except. Replace:
```python
try:
    events_raw = caldav.get_events(_date_type.today().isoformat(), days=90)
except Exception as e:
    click.echo(f"CalDAV error: {e}", err=True)
    return
```
With:
```python
# get_events never raises — degrades to [] internally on CalDAV failure
events_raw = caldav.get_events(_date_type.today().isoformat(), days=90)
```

- [ ] **Step 2: Fix `server.py` get_dump_templates (lines 233-236)**

Remove the dead try/except. Replace:
```python
if caldav:
    try:
        events = caldav.get_events(_date_type.today().isoformat(), days=30)
    except Exception:
        logger.exception("get_dump_templates: CalDAV unavailable, skipping event detection")
```
With:
```python
if caldav:
    # get_events never raises — degrades to [] internally on CalDAV failure
    events = caldav.get_events(_date_type.today().isoformat(), days=30)
```

- [ ] **Step 3: Fix `server.py` get_plan_proposal (lines 327-330)**

Remove the dead try/except. Replace:
```python
if caldav:
    try:
        events_raw = caldav.get_events(target, days=1)
        events = [{"start": e.start, "end": e.end, "title": e.title} for e in events_raw]
    except Exception:
        logger.exception("get_plan_proposal: CalDAV unavailable, planning without calendar")
```
With:
```python
if caldav:
    # get_events never raises — degrades to [] internally on CalDAV failure
    events_raw = caldav.get_events(target, days=1)
    events = [{"start": e.start, "end": e.end, "title": e.title} for e in events_raw]
```

- [ ] **Step 4: Run all tests to verify nothing broke**

```bash
uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/cli.py src/timeopt/server.py
git commit -m "fix: remove dead try/except blocks around get_events (which never raises)"
```

---

### Task 3: Fix push_calendar_blocks error handling in CLI

**Files:**
- Modify: `src/timeopt/cli.py` (line 420)
- Modify: `tests/test_cli.py`

**Issue:** `planner.push_calendar_blocks` raises `RuntimeError` on CalDAV write failure. The CLI has no error handling — users see a raw traceback. `server.py` wraps it correctly; CLI must too.

- [ ] **Step 1: Write failing test**

```python
def test_plan_push_caldav_failure_shows_user_friendly_error(cli_env, monkeypatch):
    """If push_calendar_blocks raises RuntimeError, CLI shows helpful error and exits non-zero."""
    import timeopt.planner as planner_mod
    import timeopt.cli as cli_mod
    conn = db.get_connection(cli_env)
    db.create_schema(conn)
    core.create_task(conn, core.TaskInput(title="Fix bug"))
    conn.close()

    mock_caldav = MagicMock()
    mock_caldav.get_events.return_value = []
    monkeypatch.setattr(cli_mod, "_get_caldav_client", lambda conn: mock_caldav)
    monkeypatch.setattr(planner_mod, "push_calendar_blocks",
                        MagicMock(side_effect=RuntimeError("CalDAV write failed: 503")))

    from click.testing import CliRunner
    from timeopt.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["plan", "--push"], input="y\n")
    assert result.exit_code != 0
    assert "Error" in result.output or "CalDAV" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_cli.py::test_plan_push_caldav_failure_shows_user_friendly_error -v
```

- [ ] **Step 3: Fix cli.py (line 420)**

Replace:
```python
planner.push_calendar_blocks(conn, proposal, target, caldav)
click.echo(f"Pushed {len(blocks)} block(s) to calendar.")
```
With:
```python
try:
    planner.push_calendar_blocks(conn, proposal, target, caldav)
except RuntimeError as e:
    click.echo(f"Error pushing to calendar: {e}", err=True)
    raise SystemExit(1)
click.echo(f"Pushed {len(blocks)} block(s) to calendar.")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_cli.py::test_plan_push_caldav_failure_shows_user_friendly_error -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/cli.py tests/test_cli.py
git commit -m "fix(cli): catch RuntimeError from push_calendar_blocks and show user-friendly error"
```

---

### Task 4: Fix setup wizard broad except + day_start/day_end + core.py KeyError

**Files:**
- Modify: `src/timeopt/cli.py` (lines 287-290)
- Modify: `src/timeopt/planner.py` (lines 172-173)
- Modify: `src/timeopt/core.py` (lines 548-554)
- Modify: `tests/test_cli.py`, `tests/test_planner.py`, `tests/test_core.py`

**Issues:**
1. Setup wizard's `except Exception` over all lines 215-286 catches `click.Abort` (Ctrl+C) and mislabels it as "Error saving configuration"
2. `planner.get_plan_proposal`: `day_start`/`day_end` parsed without try/except — invalid format raises unhandled ValueError
3. `core.try_resolve_unresolved`: catches `ValueError` but not `KeyError` — if `calendar_fuzzy_min_score` is removed from defaults, it crashes

- [ ] **Step 1: Write failing tests**

For `day_start`/`day_end` bad config (test_planner.py):
```python
def test_get_plan_proposal_bad_day_start_uses_default(tmp_path):
    """If day_start config is invalid, planning uses defaults and does not crash."""
    conn = db.get_connection(str(tmp_path / "test.db"))
    db.create_schema(conn)
    core.set_config(conn, "day_start", "9am_invalid")
    # Should not raise ValueError
    result = planner.get_plan_proposal(conn, [], date="2026-04-10")
    assert "blocks" in result
    assert "deferred" in result
    conn.close()
```

For `try_resolve_unresolved` KeyError (test_core.py):
```python
def test_try_resolve_unresolved_handles_keyerror_for_removed_config(tmp_path):
    """try_resolve_unresolved must not crash if calendar_fuzzy_min_score config key is missing."""
    from unittest.mock import patch
    conn = db.get_connection(str(tmp_path / "test.db"))
    db.create_schema(conn)
    # Simulate config key being removed from defaults
    with patch.object(core, "get_config", side_effect=KeyError("calendar_fuzzy_min_score")):
        result = core.try_resolve_unresolved(conn, [])
    assert isinstance(result, list)
    conn.close()
```

For setup wizard Abort (test_cli.py — difficult to test directly, check that non-DB exception re-raises):
```python
def test_setup_wizard_keyboard_interrupt_propagates(cli_env):
    """Setup wizard should not swallow KeyboardInterrupt (via click.Abort)."""
    from click.testing import CliRunner
    from timeopt.cli import cli
    from unittest.mock import patch
    import click as _click
    runner = CliRunner()
    # Simulate click.Abort during a prompt — it should NOT be labeled "Error saving configuration"
    with patch("click.confirm", side_effect=_click.exceptions.Abort()):
        result = runner.invoke(cli, ["setup"])
    # Aborted commands exit with code 1 or show "Aborted" — NOT "Error saving configuration"
    assert "Error saving configuration" not in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_planner.py::test_get_plan_proposal_bad_day_start_uses_default tests/test_core.py::test_try_resolve_unresolved_handles_keyerror_for_removed_config tests/test_cli.py::test_setup_wizard_keyboard_interrupt_propagates -v
```

- [ ] **Step 3: Fix `planner.py` day_start/day_end (lines 172-173)**

Replace:
```python
day_start = _parse_time(date, config["day_start"])
day_end = _parse_time(date, config["day_end"])
```
With:
```python
try:
    day_start = _parse_time(date, config["day_start"])
    day_end = _parse_time(date, config["day_end"])
except ValueError:
    logger.warning(
        "get_plan_proposal: invalid day_start/day_end config ('%s'/'%s'), using defaults 09:00-18:00",
        config.get("day_start"), config.get("day_end"),
    )
    day_start = _parse_time(date, "09:00")
    day_end = _parse_time(date, "18:00")
```

- [ ] **Step 4: Fix `core.py` try_resolve_unresolved (lines 548-554)**

Replace:
```python
except ValueError:
    logger.warning(
        "try_resolve_unresolved: calendar_fuzzy_min_score is not a valid integer, using default 50"
    )
    min_score = 50
```
With:
```python
except (ValueError, KeyError):
    logger.warning(
        "try_resolve_unresolved: calendar_fuzzy_min_score is not a valid integer, using default 50"
    )
    min_score = 50
```

- [ ] **Step 5: Fix `cli.py` setup wizard (lines 287-290)**

Replace:
```python
except Exception as e:
    logger.exception("setup: wizard failed")
    click.echo(f"Error saving configuration: {e}", err=True)
    raise SystemExit(1)
```
With:
```python
except (click.exceptions.Abort, click.exceptions.Exit):
    raise  # let click handle user interrupts naturally
except Exception as e:
    logger.exception("setup: wizard failed")
    click.echo(f"Error saving configuration: {e}", err=True)
    raise SystemExit(1)
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/test_planner.py tests/test_core.py tests/test_cli.py -v --tb=short 2>&1 | tail -30
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/timeopt/cli.py src/timeopt/planner.py src/timeopt/core.py tests/test_cli.py tests/test_planner.py tests/test_core.py
git commit -m "fix: guard day_start/day_end parsing, catch KeyError in try_resolve_unresolved, fix setup wizard Abort"
```

---

### Task 5: Fix server.get_config missing ok:False + add missing tests

**Files:**
- Modify: `src/timeopt/server.py` (line 199)
- Modify: `tests/test_server.py`
- Modify: `tests/test_llm.py`
- Modify: `tests/test_planner.py`

**Issues:**
1. `server.get_config` returns `{"error": ...}` without `"ok": False` — breaks CLAUDE.md invariant #1
2. No test that `OpenAICompatibleClient.complete()` passes `max_tokens` to OpenAI API
3. No test for `break_duration_min` bad-value fallback in planner
4. Weak assertion in `test_done_command_bad_fuzzy_config_uses_default`

- [ ] **Step 1: Write failing tests**

In `tests/test_server.py`:
```python
def test_get_config_unknown_key_returns_ok_false(server_env):
    """get_config with unknown key must return {ok: False, error: ...}."""
    result = server.get_config(key="completely_unknown_key_xyz")
    assert result.get("ok") is False
    assert "error" in result
```

In `tests/test_llm.py`:
```python
def test_openai_compatible_client_passes_max_tokens():
    """OpenAICompatibleClient.complete() must pass max_tokens to chat.completions.create."""
    mock_openai = MagicMock()
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "result text"
    mock_openai.return_value.chat.completions.create.return_value = mock_response

    with patch("timeopt.llm_client.openai.OpenAI", mock_openai):
        from timeopt.llm_client import OpenAICompatibleClient
        client = OpenAICompatibleClient(
            base_url="http://localhost:11434/v1",
            api_key="ollama",
            model="llama3",
            max_tokens=512,
        )
        result = client.complete("system prompt", "user message")

    assert result == "result text"
    call_kwargs = mock_openai.return_value.chat.completions.create.call_args
    assert call_kwargs.kwargs.get("max_tokens") == 512
```

In `tests/test_planner.py`:
```python
def test_get_plan_proposal_bad_break_duration_uses_default(tmp_path):
    """If break_duration_min config is invalid, planner uses default 15 and does not crash."""
    conn = db.get_connection(str(tmp_path / "test.db"))
    db.create_schema(conn)
    core.set_config(conn, "break_duration_min", "not_a_number")
    result = planner.get_plan_proposal(conn, [], date="2026-04-10")
    assert "blocks" in result
    assert "deferred" in result
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_server.py::test_get_config_unknown_key_returns_ok_false tests/test_llm.py::test_openai_compatible_client_passes_max_tokens tests/test_planner.py::test_get_plan_proposal_bad_break_duration_uses_default -v
```

- [ ] **Step 3: Fix server.py get_config (line 199)**

Replace:
```python
except KeyError:
    return {"error": f"Unknown config key: {key}"}
```
With:
```python
except KeyError:
    return {"ok": False, "error": f"Unknown config key: {key}"}
```

- [ ] **Step 4: Fix weak assertion in test_cli.py**

Find and replace the weak assertion in `test_done_command_bad_fuzzy_config_uses_default`:
```python
# OLD (weak — third clause always true):
assert result.exit_code == 0 or "Error" not in result.output or result.exit_code != 2

# NEW (strong — actually asserts no crash):
assert result.exit_code == 0
assert "ValueError" not in (result.output + str(result.exception or ""))
```

- [ ] **Step 5: Run all tests**

```bash
uv run pytest tests/test_server.py tests/test_llm.py tests/test_planner.py tests/test_cli.py -v --tb=short 2>&1 | tail -30
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/timeopt/server.py tests/test_server.py tests/test_llm.py tests/test_planner.py tests/test_cli.py
git commit -m "fix(server): add ok:False to get_config error response; add missing tests for max_tokens and break_duration_min"
```

---

### Task 6: Narrow except in caldav_client + guard import uvicorn

**Files:**
- Modify: `src/timeopt/caldav_client.py` (lines 133-140)
- Modify: `src/timeopt/cli.py` (lines 497, 518)

**Issues:**
1. `caldav_client.py` UID read uses `except Exception` — should be narrowed to `(AttributeError, ValueError, KeyError)`
2. `cli.py` `ui` command: `import uvicorn` outside try/except — `ModuleNotFoundError` gets raw traceback

- [ ] **Step 1: Write failing test for uvicorn import error**

```python
def test_ui_command_uvicorn_not_installed_shows_helpful_error(cli_env, monkeypatch):
    """If uvicorn is not installed, ui command shows a helpful error message."""
    import sys
    from click.testing import CliRunner
    from timeopt.cli import cli
    # Simulate uvicorn not installed
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    runner = CliRunner()
    result = runner.invoke(cli, ["ui"])
    assert result.exit_code != 0
    assert "uvicorn" in result.output.lower() or "install" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_cli.py::test_ui_command_uvicorn_not_installed_shows_helpful_error -v
```

- [ ] **Step 3: Fix `caldav_client.py` (narrow except)**

In `create_event`, find:
```python
except Exception:
    logger.warning(
        "create_event: could not read server UID for '%s', using generated uid=%s",
        title, uid
    )
    server_uid = uid
```
Replace with:
```python
except (AttributeError, ValueError, KeyError):
    logger.warning(
        "create_event: could not read server UID for '%s', using generated uid=%s",
        title, uid
    )
    server_uid = uid
```

- [ ] **Step 4: Fix `cli.py` ui command import uvicorn**

Find the `ui` command function. The `import uvicorn` at line 497 is inside the function. Add import error handling:
```python
try:
    import uvicorn
except ImportError:
    click.echo(
        "Error: uvicorn is required for the web UI. "
        "Install it with: pip install uvicorn[standard]",
        err=True,
    )
    raise SystemExit(1)
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_cli.py::test_ui_command_uvicorn_not_installed_shows_helpful_error tests/test_caldav.py -v
```
Expected: all pass.

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/timeopt/caldav_client.py src/timeopt/cli.py tests/test_cli.py
git commit -m "fix: narrow except in caldav UID read; guard import uvicorn with helpful error message"
```

---

## File Summary

| File | Action | Purpose |
|---|---|---|
| `src/timeopt/ui_server.py` | Modify | Mask sensitive keys in HTML rendering + POST response; fix KeyError str() |
| `src/timeopt/cli.py` | Modify | Remove dead try/except in sync; fix push error handling; fix setup wizard Abort; guard uvicorn import |
| `src/timeopt/server.py` | Modify | Remove dead try/except in get_dump_templates and get_plan_proposal; add ok:False to get_config |
| `src/timeopt/planner.py` | Modify | Guard day_start/day_end parsing with fallback |
| `src/timeopt/core.py` | Modify | Catch KeyError (not just ValueError) in try_resolve_unresolved |
| `src/timeopt/caldav_client.py` | Modify | Narrow except Exception to specific types in UID read |
| `tests/test_ui_server.py` | Modify | Add tests for sensitive masking in HTML and POST response |
| `tests/test_server.py` | Modify | Add test for get_config ok:False |
| `tests/test_llm.py` | Modify | Add test for OpenAICompatibleClient max_tokens passthrough |
| `tests/test_planner.py` | Modify | Add tests for break_duration_min and day_start/day_end bad config |
| `tests/test_core.py` | Modify | Add test for try_resolve_unresolved KeyError handling |
| `tests/test_cli.py` | Modify | Fix weak assertion; add push error test; add setup wizard Abort test; add uvicorn import test |
