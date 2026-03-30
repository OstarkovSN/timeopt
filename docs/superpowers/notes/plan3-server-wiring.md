# Plan 3: Server Wiring Notes

Key decisions required when wiring Plan 1 + 2 functions into the MCP server and CLI.

---

## ⚠️ Plan document code is wrong in several places — follow these notes, not the plan

The code snippets in `2026-03-28-interfaces.md` have the following known errors. The correct behavior is documented below (and in plan2-api-contracts.md). When you see a conflict, **these notes win**.

| Plan code error | Correct behavior |
|---|---|
| `server.list_tasks` returns `core.list_tasks(...)` bare | Must return `{"tasks": list}` |
| `server.fuzzy_match_tasks` returns bare list | Must return `{"candidates": list}` |
| `server.classify_tasks` returns bare list | Must return `{"tasks": list}` |
| Mutation tools (`mark_done`, `mark_delegated`, etc.) return `None` | Must catch `ValueError`, return `{"ok": True}` or `{"error": str(e)}` |
| `test_get_task` passes `display_id` as `task_id` | `core.get_task` is UUID-only; test must fetch UUID first |
| `cli._print_tasks(result)` calls `result.get("tasks")` on `core.list_tasks` return | `core.list_tasks` returns a bare `list` — CLI must call it directly, not wrap in `_print_tasks` expecting a dict |

---

## CalendarEvent → dict conversion for get_plan_proposal

`planner.get_plan_proposal` takes `events: list[dict]` with format `{"start": "ISO8601", "end": "ISO8601", "title": "..."}`.

`caldav_client.get_events()` returns `list[CalendarEvent]` objects (with `.start`, `.end`, `.title`, `.uid` attributes).

**Must convert before calling:**
```python
events_raw = caldav.get_events(target_date, days=1)
events_dicts = [{"start": e.start, "end": e.end, "title": e.title} for e in events_raw]
proposal = planner.get_plan_proposal(conn, events_dicts, target_date)
```

---

## Error handling in server tools

All core mutation functions raise `ValueError`. Server tools must catch:

```python
@mcp.tool()
def update_task_notes(task_id: str, notes: str) -> dict:
    conn = _open_conn()
    try:
        core.update_task_notes(conn, task_id, notes)
        return {"ok": True}
    except ValueError as e:
        return {"error": str(e)}
    finally:
        conn.close()
```

Apply same pattern to: `mark_done`, `mark_delegated`, `return_to_pending`, `get_task` (raises ValueError if not found), `get_config` (raises KeyError for unknown keys).

---

## dump_task server tool: querying for UUID

`core.dump_task(conn, task_input)` returns only `display_id` (string). But the server tool's tests expect `{"display_id": ..., "id": ...}`. After calling core, query for the UUID:

```python
display_id = core.dump_task(conn, task_input)
row = conn.execute("SELECT id FROM tasks WHERE display_id=?", (display_id,)).fetchone()
return {"display_id": display_id, "id": row[0] if row else None}
```

---

## push_calendar_blocks: proposal wrapping

`planner.push_calendar_blocks(conn, proposal, date, caldav_client)` expects `proposal = {"blocks": [...]}`.

The MCP tool receives `blocks` as a bare list. Must wrap:
```python
planner.push_calendar_blocks(conn, {"blocks": blocks}, target_date, caldav)
```

---

## _get_caldav helper: all CalDAV config keys

CalDAV config keys that may return None (no defaults):
- `caldav_url` → fall back to `"https://caldav.yandex.ru"` if None
- `caldav_username` → None means CalDAV not configured
- `caldav_password` → None means CalDAV not configured
- `caldav_read_calendars` → fall back to `"all"` if None
- `caldav_tasks_calendar` → fall back to `"Timeopt"` if None

If username or password is None, return None (not an error — CalDAV is optional).

---

## CalDAV graceful degradation

All tools that need CalDAV must handle it being unconfigured:

```python
caldav = _get_caldav(conn)
if not caldav:
    return {"events": [], "warning": "CalDAV not configured"}
```

For `get_plan_proposal`: CalDAV unavailable is a warning, not a hard failure — pass `events=[]` to still generate a plan.

For `push_calendar_blocks`, `sync_calendar`, `resolve_calendar_reference`: return `{"ok": False, "error": "CalDAV not configured"}`.

---

## cli_dump: LLM prompt structure

`core.cli_dump(conn, llm_client, raw_text)` added in Plan 3. It:
1. Splits `raw_text` on `, ;` and word `and`
2. Calls `core.get_dump_templates(fragments, events=[])` (no CalDAV in CLI)
3. Sends system + user prompt to LLM
4. Parses JSON array from LLM response with `_parse_json_array()`
5. Builds `TaskInput` for each filled dict
6. Calls `core.dump_tasks(conn, task_inputs)`
7. Returns `{"count": N, "display_ids": [...]}`

The `_parse_json_array` helper uses `re.search(r'\[[\s\S]*\]', text)` to find a JSON array anywhere in LLM response (handles markdown preamble).

---

## get_config KeyError handling

`core.get_config(conn, key)` raises `KeyError` for unknown keys. The server `get_config` tool calls it with a user-supplied `key`. If `key` is in `_CONFIG_DEFAULTS` or is a CalDAV/LLM key, it's fine. But if someone passes an unknown key, it will raise.

The server tool should catch `KeyError`:
```python
try:
    return {"key": key, "value": core.get_config(conn, key)}
except KeyError:
    return {"error": f"Unknown config key: {key}"}
```

---

## task_id scope: UUID vs display_id

| Function | Accepts |
|---|---|
| `core.mark_done` | UUID or display_id |
| `core.mark_delegated` | UUID or display_id |
| `core.update_task_notes` | UUID only |
| `core.return_to_pending` | UUID only |
| `core.get_task` | UUID only |
| `core.fuzzy_match_tasks` | — (returns task_id UUID in results) |

Server tools for `update_task_notes`, `return_to_pending`, and `get_task` should document that they require UUIDs. The typical flow is: call `fuzzy_match_tasks` → get `task_id` (UUID) → pass to these functions.

---

## list_tasks: notes field truncation

`core.list_tasks` truncates `notes` to the **last 60 characters** for display. This is intentional — it shows the most recent log entry inline. For full notes, call `core.get_task(conn, task_id)`.

---

## DB path convention

Both server and CLI use `TIMEOPT_DB` env var with fallback:
```python
_DEFAULT_DB = str(Path.home() / ".timeopt" / "tasks.db")

def _db_path() -> str:
    return os.environ.get("TIMEOPT_DB", _DEFAULT_DB)
```

Tests inject a temp path via `patch.dict(os.environ, {"TIMEOPT_DB": db_path})`.

The server function `_open_conn()` must call `create_schema(conn)` to be idempotent — safe to call on every server request since `create_schema` uses `CREATE TABLE IF NOT EXISTS`.
