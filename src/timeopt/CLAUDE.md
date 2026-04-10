# src/timeopt — Module Context

## File Responsibilities

| File | Owns |
|---|---|
| `db.py` | `get_connection`, `create_schema`, `next_short_id` — nothing else |
| `core.py` | Task CRUD, config get/set, LLM dump pipeline (`cli_dump`, `get_dump_templates`), sync helpers |
| `planner.py` | Eisenhower classification, free-slot computation, scheduling, CalDAV push (`push_calendar_blocks`) |
| `caldav_client.py` | `CalDAVClient`: `get_events`, `create_event`, `delete_event` |
| `llm_client.py` | `AnthropicClient`, `OpenAICompatibleClient`, `build_llm_client` |
| `server.py` | FastMCP wiring only — no business logic. Opens/closes conn per call. |
| `cli.py` | click CLI — calls core/planner, converts return shapes for display |

## Invariants That Cause Bugs If Broken

**Return shapes — core vs server differ:**
- `core.list_tasks(conn)` → bare `list[dict]`
- `server.list_tasks()` → `{"tasks": list}` (wrapped)
- `core.fuzzy_match_tasks(conn, query)` → bare `list[dict]`
- `server.fuzzy_match_tasks(query)` → `{"candidates": list}` (wrapped)
- `cli.py` calls core directly, so it gets bare lists — don't add wrapping

**UUID vs display_id scope:**
- `mark_done` / `mark_delegated` accept either UUID or display_id (queries `WHERE id=? OR display_id=?`)
- `get_task`, `update_task_notes`, `return_to_pending` — UUID only, raise `ValueError` if not found
- Always use `fuzzy_match_tasks` → `task_id` field before calling UUID-only functions

**CalDAV graceful degradation:**
- `_get_caldav(conn)` returns `None` when `caldav_username` or `caldav_password` is unset
- All server tools that need CalDAV must check `if not caldav: return {..., "error": "..."}` or `"warning"` for read-only tools
- Never let a missing CalDAV config propagate as an exception

**Config errors:**
- `core.get_config` raises `KeyError` (not `ValueError`) for unknown keys
- `server.get_config` catches `KeyError` separately — don't change to `ValueError`
- Optional config keys (`caldav_*`, `llm_*`) return `None` when unset — not a KeyError

**push_calendar_blocks transaction order:**
1. Collect old UIDs from DB (before changes)
2. All CalDAV creates first (may raise — leaves DB untouched)
3. Delete old CalDAV events (best-effort)
4. SQLite commit atomically
- If a CalDAV create fails partway, orphaned events are left in Yandex Calendar — this is a known limitation, not a bug to silently fix

**Scheduling break behavior:**
- `get_plan_proposal` always adds `break_duration_min` after each block, including the last
- A task that exactly fills the remaining slot will be **deferred** if `break_duration_min > 0`
- This is intentional behavior; tests should assert it explicitly

**`_parse_json_array` uses greedy regex `\[[\s\S]*\]`:**
- Matches from first `[` to last `]` — if LLM returns two JSON arrays, it spans both
- `json.JSONDecodeError` (subclass of `ValueError`) bubbles up to CLI as unhandled exception

## Key Patterns

**Every server tool:** opens conn in `_open_conn()`, wraps mutations in `try/except ValueError → {"error": str(e)}`, closes in `finally`.

**CalendarEvent objects vs dicts:** `caldav_client` returns `CalendarEvent` dataclass objects. `planner.get_plan_proposal` and `core.sync_bound_tasks` expect `list[dict]` with `{start, end, title}`. Server converts: `{"start": e.start, "end": e.end, "title": e.title}` — always do this conversion at the server boundary, not inside core/planner.
