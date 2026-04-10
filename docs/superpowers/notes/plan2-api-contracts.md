# Plan 2 API Contracts

Exact signatures and return types for everything added in Plan 2. Plan 3 implementers depend on these.

## Note: `get_config` / `get_all_config` already patched

`core.get_config` and `core.get_all_config` now support `caldav_*` and `llm_*` keys — they return `None` if unset (no KeyError). This was a gap in Plan 1 that was fixed before Plan 2 started. Plan 2 implementers can call `get_config(conn, "caldav_url")` etc. without needing to patch core first.

---

## `src/timeopt/llm_client.py`

```python
class LLMClient:
    def complete(self, system: str, user: str) -> str: ...

class AnthropicClient(LLMClient):
    def __init__(self, api_key: str | None, model: str)
    # Raises ValueError("ANTHROPIC_API_KEY") if api_key=None and env var not set

class OpenAICompatibleClient(LLMClient):
    def __init__(self, base_url: str, api_key: str, model: str)

def build_llm_client(config: dict) -> LLMClient
# config: dict from get_all_config(conn)
# Uses OpenAICompatibleClient if config["llm_base_url"] is set, else AnthropicClient
# Raises ValueError if no API key available
```

---

## `src/timeopt/caldav_client.py`

```python
@dataclass
class CalendarEvent:
    uid: str
    title: str
    start: str  # ISO8601 UTC string e.g. "2026-03-28T09:00:00+00:00"
    end: str    # ISO8601 UTC string

class CalDAVClient:
    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        read_calendars: str = "all",   # "all" or comma-separated calendar names
        tasks_calendar: str = "Timeopt",
    )

    def get_events(self, date: str, days: int = 1) -> list[CalendarEvent]
    # date: "YYYY-MM-DD" string
    # Returns [] on connection failure (warns, does NOT raise)
    # Skips the tasks_calendar (never reads own write calendar)

    def create_event(self, title: str, start: str, end: str) -> str
    # start/end: ISO8601 strings
    # Returns caldav_uid string of created event
    # Raises on CalDAV failure

    def delete_event(self, caldav_uid: str) -> None
    # Logs exception on failure, does NOT raise

    def _ensure_tasks_calendar(self, principal) -> calendar_obj
    # Creates Timeopt calendar if it doesn't exist
```

---

## `src/timeopt/core.py` additions (Plan 2)

```python
def get_dump_templates(fragments: list[str], events: list) -> dict
# events: list[CalendarEvent] objects (from caldav_client.get_events())
# Returns:
# {
#   "schema": {"priority": "high|medium|low", "urgent": "bool", ...},
#   "templates": [
#     {"raw": "...", "title": "...", "priority": "?", "urgent": "?",
#      "category": "?", "effort": "?",
#      # optional only if detected:
#      "due_at": "?",
#      "due_event_label": "...",   # pre-filled label
#      "due_event_offset_min": "?",
#      "_resolved_event_uid": "..."  # pre-resolved if found in events
#     }, ...
#   ]
# }
# Nullable due_* fields OMITTED from template if not detected

def resolve_calendar_reference(label: str, events: list) -> dict | None
# events: list[CalendarEvent] objects
# Returns {uid, title, start, end, score} or None if no match (score < 50)

def dump_task(conn, task: TaskInput) -> str
# !! Returns display_id STRING, NOT a dict !!
# Auto-runs _auto_classify() after insert

def dump_tasks(conn, tasks: list[TaskInput]) -> list[str]
# !! Returns list[str] of display_ids, NOT {"count": N, "display_ids": [...]} !!
# Auto-runs _auto_classify() once after all inserts

def sync_bound_tasks(conn, events: list) -> list[dict]
# events: list[CalendarEvent] objects
# Only touches tasks with due_event_uid IS NOT NULL AND status IN pending/delegated
# Returns list of changes:
#   {"display_id", "old_due_at", "new_due_at", "status": "updated"|"event_missing"}

def get_unresolved_tasks(conn) -> list[dict]
# Returns [{id, display_id, due_event_label}] for due_unresolved=True tasks

def try_resolve_unresolved(conn, events: list) -> list[dict]
# events: list[CalendarEvent] objects
# Returns [{"display_id", "status": "resolved"|"still_unresolved"}]
```

---

## `src/timeopt/planner.py` additions (Plan 2)

```python
def push_calendar_blocks(
    conn,
    proposal: dict,       # {"blocks": [...]} — same shape as get_plan_proposal return
    date: str,            # "YYYY-MM-DD"
    caldav_client,        # CalDAVClient instance
) -> None
# !! proposal must be {"blocks": [...]}, NOT a bare list !!
# Transactional: CalDAV writes first, SQLite only on full success
# Raises if CalDAV fails — leaves DB unchanged
# Deletes old calendar_blocks for date before inserting new ones
# Uses _get_uids_for_date() internally to find old CalDAV UIDs to delete
```

---

## Critical format mismatch summary

These core functions return plain Python types. The MCP server tools in Plan 3 **must wrap them**:

| Core function | Returns | Server tool must return |
|---|---|---|
| `core.list_tasks()` | `list[dict]` | `{"tasks": list[dict]}` |
| `core.fuzzy_match_tasks()` | `list[dict]` | `{"candidates": list[dict]}` |
| `planner.classify_tasks()` | `list[dict]` | `{"tasks": list[dict]}` |
| `core.mark_done()` | `None` (or raises) | `{"ok": True}` or `{"error": "..."}` |
| `core.mark_delegated()` | `None` (or raises) | `{"ok": True}` or `{"error": "..."}` |
| `core.update_task_notes()` | `None` (or raises) | `{"ok": True}` or `{"error": "..."}` |
| `core.return_to_pending()` | `None` (or raises) | `{"ok": True}` or `{"error": "..."}` |
| `core.dump_task()` | `str` (display_id) | `{"display_id": ..., "id": ...}` |
| `core.dump_tasks()` | `list[str]` | `{"count": N, "display_ids": [...]}` |

**All mutation functions raise `ValueError` on errors.** Server tools must catch ValueError and return `{"error": str(e)}`.
