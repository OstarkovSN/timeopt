# Test Coverage Gaps

Analysis of untested / undertested code as of 2026-04-01. 116 tests passing.
Organized by priority. Each block is independently addressable.

---

## Block 1: `cli_dump` + `_parse_json_array` (core.py)

**Priority: Critical**

Zero tests for both functions despite being the most complex parsing code in the project.

### What's missing
- `_parse_json_array`: regex extraction from LLM response, `json.loads`, raises `ValueError` on no match
- `cli_dump`: fragment splitting on `,;` and word `and`, template retrieval, LLM call, parse, TaskInput construction, `dump_tasks` call, return shape `{"count", "display_ids"}`
- Malformed LLM JSON (truncated, markdown-wrapped, no array at all)
- LLM returns fewer items than fragments (partial parse)
- Fragment splitting edge cases: trailing comma, "and" inside a word ("sandcastle"), semicolons

### Gotchas
- `_parse_json_array` uses greedy `[\s\S]*` — if LLM response has two JSON arrays (unlikely but possible), it will match from first `[` to last `]`, which may span both. May silently produce garbage.
- Fragment split uses `(?<!\w)and(?!\w)` — word boundary lookbehind. Test with "brand new task" (should not split on "and"), "buy milk and fix login" (should split).
- `cli_dump` calls `get_dump_templates(fragments, events=[])` with no CalDAV context — templates won't have `due_event_label` pre-filled even if the fragment mentions a calendar event. This is intentional (CLI has no CalDAV) but untested, so a future change could silently break it.

### Test approach
Mock `llm_client.complete()`. Test `_parse_json_array` standalone with fixtures: clean array, markdown-wrapped, leading text, two arrays, no array.

---

## Block 2: Server tools — CalDAV success paths

**Priority: Critical**

All 5 CalDAV-dependent server tools are tested only in "not configured" state. Their success paths are completely dark.

### What's missing
- `get_calendar_events` with mock CalDAV: returns `{"events": [{title, start, end, uid}, ...]}`
- `resolve_calendar_reference` with mock CalDAV: match found vs no match vs low-score
- `get_plan_proposal` with mock CalDAV providing events that create actual free slots
- `push_calendar_blocks` with mock CalDAV: creates events, replaces old UIDs in DB, returns `{"ok": True, "pushed": N}`
- `sync_calendar` with mock CalDAV: updated/resolved/still_unresolved paths

### Gotchas
- `get_dump_templates` fetches 30 days of events — mock needs to return `CalendarEvent` objects (not dicts). The server converts them: `{"start": e.start, "end": e.end, "title": e.title}`. Mock must match the `.start`/`.end`/`.title`/`.uid` attribute interface.
- `push_calendar_blocks` server tool wraps blocks as `{"blocks": blocks}` before calling `planner.push_calendar_blocks`. If this wrapping is ever removed, the test would catch it — but only if the success path is tested.
- CalDAV mock needs to be patched at `timeopt.server._get_caldav` or `timeopt.caldav_client.CalDAVClient`, not at the caldav library level.

### Test approach
Add a `mock_caldav` fixture that returns a `MagicMock` with `.get_events()`, `.create_event()`, `.delete_event()` methods. Patch `timeopt.server._get_caldav` to return it.

---

## Block 3: `get_plan_proposal` — actual scheduling

**Priority: Critical**

The current server test seeds no tasks. `result["blocks"]` is always `[]`. The scheduling logic (free slot computation, Eisenhower sort, effort mapping, break insertion, overflow deferral) is tested in `test_planner.py` but the **server wrapper** has never scheduled anything.

### What's missing
- Server's `get_plan_proposal` with tasks + mock CalDAV events produces populated `blocks`
- Deferred tasks when day is full
- Correct ordering (Q1 before Q2 before Q3 before Q4)
- Break insertion between blocks
- Effort mapping (small=30min, medium=60min, large=120min)

### Gotchas
- `planner.get_plan_proposal` expects `events: list[dict]` with `{"start", "end", "title"}`. The server fetches `CalendarEvent` objects and converts them. If conversion is wrong, slots are miscalculated silently.
- Events use ISO8601 UTC strings. The planner parses them with `datetime.fromisoformat(...replace("Z", "+00:00"))`. Mock events must use valid ISO8601 strings or parsing fails.
- Day start/end are read from config (`day_start="09:00"`, `day_end="18:00"`). These are treated as UTC. If a real user's timezone differs, blocks appear at wrong times — not a test gap per se but worth a comment.

### Test approach
Seed 2-3 tasks of different quadrants, provide an empty events list (no calendar blocks), assert `blocks` is non-empty and ordered correctly.

---

## Block 4: Server mutation tools — error paths

**Priority: High**

The server wraps all mutations in `try/except ValueError → {"error": str(e)}`. These error paths have no test coverage.

### What's missing
- `get_task(task_id="nonexistent-uuid")` → `{"error": "Task not found: ..."}`
- `mark_done(task_ids=["nonexistent"])` → `{"error": ...}`
- `update_task_notes` on a **pending** task (not delegated) → `{"error": ...}` — this is tested! But on a done task, untested.
- `return_to_pending` on a task that isn't delegated → `{"error": ...}`
- `get_config(key="nonexistent_key")` → `{"error": "Unknown config key: ..."}`

### Gotchas
- `mark_done` and `mark_delegated` accept display_id OR UUID. The error message differs depending on which path raises. Ensure tests cover both.
- `core.get_config` raises `KeyError` (not `ValueError`) — server catches it separately. Easy to accidentally change to `ValueError` handler if not tested.

---

## Block 5: LLM client — error paths

**Priority: High**

Only success paths are mocked. All failure modes are untested.

### What's missing
- `AnthropicClient.complete()` when Anthropic API returns 401, 429, 500
- `OpenAICompatibleClient.complete()` with bad `base_url` or wrong model name
- `build_llm_client(config)` selection: when `llm_base_url` is set → uses `OpenAICompatibleClient`; when not → uses `AnthropicClient`
- `AnthropicClient` with `ANTHROPIC_API_KEY` set in env but `llm_api_key=None` in config (should fall through to env var)

### Gotchas
- Both clients do lazy imports (`try: import anthropic/openai except ImportError`). If the library isn't installed, the import succeeds but the object is `None`, and the error surfaces at call time, not import time. This import-time vs call-time distinction is untested.
- `build_llm_client` reads `llm_model` from config (default `claude-sonnet-4-6`). If config returns `None` (optional key not set), the client must fall back to the default. Untested.

---

## Block 6: CalDAV client — failure modes

**Priority: High**

`test_caldav.py` covers connection failure for `get_events` (returns `[]`) but most other failure modes are untested.

### What's missing
- `create_event` failure → what does the caller see? (planner expects a UID back)
- `delete_event` failure → currently logs and swallows. The transactional guarantee in `push_calendar_blocks` depends on deletes being "best effort" after creates succeed — but if delete silently fails, old events remain in Yandex Calendar (orphaned). Not a crash, but a data integrity gap.
- `_ensure_tasks_calendar` when calendar creation fails (permissions)
- `get_events` partial failure: first calendar succeeds, second raises

### Gotchas
- `caldav` library is lazily imported. If not installed, `caldav = None` and `CalDAVClient.__init__` raises `ImportError`. This is tested in `test_caldav.py` setup but not for individual methods.
- `create_event` returns a UID extracted from the created component. If the CalDAV server returns the event without a UID in the response (valid per RFC), the code falls back to generating one. The fallback path is untested.

---

## Block 7: `push_calendar_blocks` — partial CalDAV failure

**Priority: High**

`test_push_blocks.py` tests the full-failure case (all creates fail). The partial failure case (N-1 creates succeed, last one fails) is untested.

### What's missing
- Creates 1-3 succeed (UIDs collected), create 4 raises → planner raises, DB not touched, but CalDAV events 1-3 were already created and are now orphaned
- Deletes fail after creates succeed → old CalDAV events survive, new ones also exist, SQLite committed → duplicate calendar entries

### Gotchas
- The current implementation does NOT roll back orphaned CalDAV creates on partial failure. This is an acknowledged limitation (not a bug in the implementation, but important to document and test the behavior). A test asserting "orphaned events exist on partial failure" would make this explicit.
- `planner.push_calendar_blocks` is not idempotent — calling it twice with the same blocks creates duplicate CalDAV events. No test covers this.

---

## Block 8: Fuzzy matching edge cases

**Priority: Medium**

`fuzzy_match_tasks` is tested for the happy path but several edge cases are untested.

### What's missing
- Empty DB → returns `[]` (currently covered in server via `list_tasks` but not `fuzzy_match_tasks` directly)
- All tasks are `done` → returns `[]` (only searches pending/delegated)
- Query matches multiple tasks with identical scores → order is undefined
- Very short query ("a") → high false-positive rate, scores still returned
- CLI `done` command with a query that matches nothing → "No confident match" message (tested) but exit code not asserted

### Gotchas
- `rapidfuzz.process.extract` returns `(title, score, index)` tuples. If the index is out of bounds in the rows list (shouldn't happen, but possible if rows mutate between calls), it silently returns wrong results. Not a practical risk but worth noting.

---

## Block 9: `get_plan_proposal` scheduling edge cases (planner.py)

**Priority: Medium**

Unit tests in `test_planner.py` cover the main scheduling path but miss several boundary conditions.

### What's missing
- Zero free slots (events fill entire day) → all tasks deferred
- Single task exactly fits remaining slot (no break needed for last item) — the code adds a break even for the last item, which may cause it to not fit when it should
- Events that start before `day_start` or end after `day_end`
- Overlapping events (two events at the same time)
- `effort=None` task → falls back to `default_effort` config

### Gotchas
- `_compute_free_slots` uses `(slot_end - cursor).seconds // 60` for available minutes. `.seconds` is not the same as `.total_seconds()` — for durations > 24h, `.seconds` wraps. Won't happen in practice (day slots < 24h) but worth knowing.
- The break is always added (`duration + break_min`) even for the last scheduled task. This means a task that exactly fills the last slot will be deferred if `break_min > 0`. Could be surprising behavior.

---

## Block 10: CLI edge cases

**Priority: Medium**

### What's missing
- `done` with multiple queries in one invocation (e.g. `timeopt done "fix login" "call dentist"`)
- `tasks --all` flag (include_old_done)
- `plan --date` with an invalid date format → should show an error, not crash
- `history --week` vs `--today` filtering boundary (task done at midnight — is it today or yesterday?)
- `config get` with an unknown key
- `dump` with multiple fragments (the LLM mock only returns one task)
- CLI exit codes: should be non-zero on errors

### Gotchas
- `history` filters `done_at` as a string comparison (`done_at >= cutoff`). This works as long as ISO8601 format is consistent, but if `done_at` is stored without timezone (`2026-04-01T10:00:00` vs `2026-04-01T10:00:00+00:00`), string comparison breaks. Currently all timestamps use UTC, but worth verifying.

---

## Block 11: DB schema constraints

**Priority: Low**

`test_db.py` confirms tables exist and `CHECK` constraints are defined, but doesn't verify they're enforced.

### What's missing
- Inserting invalid `priority` value → should raise `IntegrityError`
- Inserting invalid `status` value → should raise `IntegrityError`
- Inserting duplicate `short_id` for active tasks → partial index constraint enforced
- Foreign key: `calendar_blocks.task_id` referencing non-existent task → should raise (FK enabled via PRAGMA)

### Gotchas
- SQLite `CHECK` constraints are enforced but `FOREIGN KEY` constraints require `PRAGMA foreign_keys=ON` per connection. `db.get_connection` sets this, but if anyone opens a connection directly via `sqlite3.connect()` without going through `get_connection`, FK constraints are silently disabled.

---

## Block 12: `_parse_json_array` security / robustness

**Priority: Low**

The regex `\[[\s\S]*\]` is greedy. Combined with `json.loads`, a pathological LLM response could cause issues.

### What's missing
- Response with nested arrays → greedy match returns outermost; `json.loads` parses it correctly, but inner array items may be unexpected types
- Response with `[]` (empty array) → valid JSON, returns `[]`, `cli_dump` saves 0 tasks silently
- Extremely large response → no size limit, no timeout guard

### Gotchas
- `json.loads` in Python raises `json.JSONDecodeError` (subclass of `ValueError`) on bad JSON. The `cli_dump` caller doesn't catch this — it would propagate as an unhandled exception to the CLI user. Should be caught and shown as a user-friendly error.

---

## Recommended Test Writing Order

1. Block 1 — `_parse_json_array` + `cli_dump` unit tests (standalone, no mocks needed for parse tests)
2. Block 2 — Server CalDAV success paths (needs `mock_caldav` fixture — write once, reuse)
3. Block 3 — `get_plan_proposal` with real tasks scheduled (use same fixture)
4. Block 4 — Server error path tests (quick, one test each)
5. Block 5 — `build_llm_client` selection logic (simple unit test)
6. Block 7 — Partial CalDAV failure behavior (explicitly document the orphan behavior)
7. Blocks 8–12 — Edge cases, add alongside relevant feature work
