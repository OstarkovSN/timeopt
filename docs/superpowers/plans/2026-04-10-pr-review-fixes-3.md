# PR Review Fixes Round 3 — Implementation Plan

**Goal:** Fix remaining issues from third PR review round.

---

### Task A: Guard "***" placeholder in set_config_field + fix false-positive test + use _mask_sensitive helper

**Files:**
- Modify: `src/timeopt/ui_server.py`
- Modify: `tests/test_ui_server.py`

**Issues:**
1. (Critical) POST /api/config/llm_api_key with value "***" saves the literal mask string, destroying the real key
2. get_all_config_api duplicates masking logic — should call `_mask_sensitive(core.get_all_config(conn))`
3. server.resolve_calendar_reference catches only ValueError, not KeyError for calendar_fuzzy_min_score
4. (Test fix) False-positive assertion in test_post_config_unknown_key_error_message_not_double_quoted

Fix "***" guard:
```python
if key in core._SENSITIVE_CONFIG_KEYS and value == "***":
    return templates.TemplateResponse(
        request, "partials/config_field.html",
        {"key": key, "value": "***", "status": "saved"},
    )
core.set_config(conn, key, value)
```

Fix get_all_config_api to use helper:
```python
cfg = _mask_sensitive(core.get_all_config(conn))
return JSONResponse(content=cfg)
```

Test to write:
```python
def test_post_config_sensitive_key_with_mask_placeholder_does_not_overwrite(ui_env):
    """POST with value='***' for a sensitive key must NOT save '***' to DB."""
    conn = db.get_connection(ui_env)
    core.set_config(conn, "llm_api_key", "sk-real-key-12345")
    conn.close()
    from fastapi.testclient import TestClient
    from timeopt.ui_server import app
    client = TestClient(app)
    client.post("/api/config/llm_api_key", data={"value": "***"})
    # Verify DB still has real value
    conn2 = db.get_connection(ui_env)
    assert core.get_config(conn2, "llm_api_key") == "sk-real-key-12345"
    conn2.close()
```

Fix false-positive test assertion:
```python
# OLD (never catches regression):
# assert "\"'Unknown config key:" not in resp.text
# assert "'Unknown config key:" not in resp.text or "\"'Unknown" not in resp.text
# NEW (catches str(KeyError) regression):
assert "'Unknown config key:" not in resp.text
```

---

### Task B: Remove last dead try/except in cli.py plan + narrow server.push_calendar_blocks

**Files:**
- Modify: `src/timeopt/cli.py`
- Modify: `src/timeopt/server.py`

**Issues:**
1. `cli.py` plan command (~line 384-388) still has dead try/except around get_events (one was missed in previous cleanup)
2. `server.py` push_calendar_blocks uses `except Exception` — should be `except RuntimeError` to be consistent with CLI fix and not mask programming errors

Fix cli.py (find and remove):
```python
# Remove this:
try:
    raw_events = caldav.get_events(target, days=1)
    events = [{"start": e.start, "end": e.end, "title": e.title} for e in raw_events]
except Exception:
    logger.exception("plan: CalDAV unavailable, proceeding without calendar")
# Replace with:
if caldav:
    # get_events never raises — degrades to [] internally on CalDAV failure
    raw_events = caldav.get_events(target, days=1)
    events = [{"start": e.start, "end": e.end, "title": e.title} for e in raw_events]
```

Fix server.py push_calendar_blocks:
```python
# Change:
except Exception as e:
    logger.exception("push_calendar_blocks: failed")
    return {"ok": False, "error": str(e)}
# To:
except RuntimeError as e:
    logger.error("push_calendar_blocks: CalDAV write failed: %s", e)
    return {"ok": False, "error": str(e)}
```

No new tests needed — existing tests cover these paths.

---

### Task C: Fix server.resolve_calendar_reference to catch (ValueError, KeyError)

**Files:**
- Modify: `src/timeopt/server.py`
- Modify: `tests/test_server.py`

**Issue:** `server.resolve_calendar_reference` has `except ValueError` around `int(core.get_config(..., "calendar_fuzzy_min_score"))` but should also catch `KeyError` (consistent with the fix already applied to `core.try_resolve_unresolved`).

Test to write:
```python
def test_resolve_calendar_reference_keyerror_for_config_uses_default(server_env):
    """resolve_calendar_reference must not crash if get_config raises KeyError."""
    from unittest.mock import patch
    with patch("timeopt.core.get_config", side_effect=KeyError("calendar_fuzzy_min_score")):
        result = server.resolve_calendar_reference(label="meeting", date_range=7)
    assert "candidates" in result
    assert "error" not in result
```

Fix in server.py: change `except ValueError:` to `except (ValueError, KeyError):` in resolve_calendar_reference.
