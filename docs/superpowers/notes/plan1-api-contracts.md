# Plan 1 API Contracts

Exact signatures and return types for everything built in Plan 1. Plan 2 and Plan 3 implementers depend on these.

---

## `src/timeopt/db.py`

```python
def get_connection(path: str = None) -> sqlite3.Connection
# path=":memory:" for tests; None = default ~/.timeopt/timeopt.db
# row_factory = sqlite3.Row (rows accessible by column name)
# WAL mode enabled for file DBs; foreign_keys=ON

def create_schema(conn) -> None
# idempotent — safe to call on every startup

def next_short_id(conn) -> int
# Returns lowest free int from 1–99 not held by any pending/delegated task.
# Falls back to MAX(short_id)+1 (≥100) if 1–99 all occupied.
```

**`tests/conftest.py` `conn` fixture:**
```python
@pytest.fixture
def conn():
    c = get_connection(":memory:")
    create_schema(c)
    yield c
    c.close()
```

---

## `src/timeopt/core.py`

### Config

```python
def get_config(conn, key: str) -> str
# Returns string value. Raises KeyError for unknown keys.
# Known keys: day_start, day_end, break_duration_min, default_effort,
#   effort_small_min, effort_medium_min, effort_large_min, hide_done_after_days,
#   fuzzy_match_min_score, fuzzy_match_ask_gap, delegation_max_tool_calls,
#   caldav_url, caldav_username, caldav_password, caldav_read_calendars,
#   caldav_tasks_calendar, llm_base_url, llm_api_key, llm_model
# Defaults: day_start="09:00", day_end="18:00", break_duration_min="15",
#   default_effort="medium", effort_small_min="30", effort_medium_min="60",
#   effort_large_min="120", hide_done_after_days="7",
#   fuzzy_match_min_score="80", fuzzy_match_ask_gap="10",
#   delegation_max_tool_calls="10"
# NOTE: caldav_* and llm_* keys have no default — return None if unset

def set_config(conn, key: str, value: str) -> None
# Raises KeyError for unknown keys.

def get_all_config(conn) -> dict[str, str]
# Returns all keys merged with DB overrides. Returns None for unset caldav_*/llm_* keys.
```

### TaskInput dataclass

```python
@dataclass
class TaskInput:
    title: str
    raw: str
    priority: str          # "high" | "medium" | "low"
    urgent: bool
    category: str          # "work" | "personal" | "errands" | "other"
    effort: str | None = None          # "small" | "medium" | "large"
    due_at: str | None = None          # ISO8601 UTC string
    due_event_uid: str | None = None
    due_event_label: str | None = None
    due_event_offset_min: int | None = None
    due_unresolved: bool = False
```

### Task operations

```python
def create_task(conn, task: TaskInput) -> str
# Returns display_id string e.g. "#1-fix-login-bug"
# Assigns short_id via next_short_id(), slugifies title for display_id

def mark_done(conn, task_ids: list[str]) -> None
# task_ids: list of UUIDs OR display_ids (both accepted)
# Raises ValueError("Task not found") if ID not found
# Raises ValueError("not active") if task is already done

def mark_delegated(conn, task_id: str, notes: str | None = None) -> None
# task_id: UUID OR display_id
# Raises ValueError("Pending task not found") if task is not pending

def update_task_notes(conn, task_id: str, notes: str) -> None
# task_id: UUID ONLY (not display_id)
# Raises ValueError("not delegated") if task status != "delegated"
# Appends timestamped entry, never overwrites

def return_to_pending(conn, task_id: str, notes: str) -> None
# task_id: UUID ONLY (not display_id)
# Raises ValueError("Delegated task not found") if not delegated
```

### Query operations

```python
def list_tasks(
    conn,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    include_old_done: bool = False,
) -> list[dict]
# !! Returns plain list[dict], NOT {"tasks": [...]} !!
# Default: pending + delegated + done within hide_done_after_days
# Each dict has ONLY display fields:
#   display_id, title, priority, urgent, category, effort,
#   due_at, status, due_event_label, due_unresolved, notes (last 60 chars)
# Calls _auto_classify() before returning

def get_task(conn, task_id: str) -> dict
# task_id: UUID ONLY (not display_id)
# Returns full row dict including raw, created_at, id, short_id, etc.
# Raises ValueError("Task not found") if not found

def fuzzy_match_tasks(conn, query: str, limit: int = 5) -> list[dict]
# !! Returns plain list[dict], NOT {"candidates": [...]} !!
# Only searches pending + delegated tasks
# Each dict: {task_id, display_id, title, score}
# Sorted by score descending
```

---

## `src/timeopt/planner.py`

```python
class EisenhowerQ(str, Enum):
    Q1 = "Q1"  # urgent + important (high/medium priority)
    Q2 = "Q2"  # important, not urgent
    Q3 = "Q3"  # urgent, not important (low priority)
    Q4 = "Q4"  # neither

def eisenhower_quadrant(priority: str, urgent: bool) -> EisenhowerQ

def classify_tasks(conn, task_ids: list[str] | None = None) -> list[dict]
# !! Returns plain list[dict], NOT {"tasks": [...]} !!
# Each dict: {task_id, display_id, title, priority, urgent, effort, due_at, quadrant}
# Sorted by quadrant: Q1 → Q2 → Q3 → Q4
# Auto-upgrades urgency for overdue/due-today tasks

def get_plan_proposal(conn, events: list[dict], date: str | None = None) -> dict
# events: list of {"start": "ISO8601", "end": "ISO8601", "title": "..."} dicts
# !! NOT CalendarEvent objects — must convert before calling !!
# Returns {"blocks": [...], "deferred": [...]}
#   block: {task_id, display_id, title, start, duration_min, quadrant}
#   deferred: {task_id, display_id, title, quadrant}
# date: "YYYY-MM-DD" string, defaults to today UTC

def save_calendar_blocks(conn, blocks: list[dict], plan_date: str, caldav_uids: list[str]) -> None
# caldav_uids must be same length and order as blocks

def delete_calendar_blocks_for_date(conn, plan_date: str) -> list[str]
# Returns list of caldav_uids that were deleted (caller must delete from CalDAV)

def get_calendar_blocks(conn, plan_date: str) -> list[dict]
# Each dict: {id, task_id, caldav_uid, scheduled_at, duration_min, plan_date}
```
