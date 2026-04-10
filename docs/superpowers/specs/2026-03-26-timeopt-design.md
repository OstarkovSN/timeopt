# Timeopt — Design Spec
**Date:** 2026-03-26

## Overview

A Claude Code plugin that acts as a personal task manager with Yandex Calendar integration. Lets the user brain-dump tasks in free-form text, organizes them by priority using the Eisenhower matrix, and generates a realistic time-blocked daily schedule around existing calendar commitments.

---

## Architecture

Three interface layers on top of a shared Core API:

```
┌─────────────────────────────────────────────┐
│               timeopt backend               │
│                                             │
│  ┌──────────┐   ┌──────────┐   ┌─────────┐ │
│  │  SQLite  │   │  Planner │   │  CalDAV │ │
│  │   DB     │   │  Engine  │   │  Client │ │
│  └────┬─────┘   └────┬─────┘   └────┬────┘ │
│       └──────────────┴──────────────┘       │
│                   Core API                  │
│         ┌──────────────────────┐            │
│         │      LLM Client      │            │
│         │ (Anthropic / OpenAI) │            │
│         └──────────────────────┘            │
│       ┌──────────┬─────────────┐            │
│  ┌────┴───┐  ┌───┴───┐  ┌─────┴──────┐     │
│  │  MCP   │  │  CLI  │  │  Telegram  │     │
│  │ Server │  │(click)│  │  (future)  │     │
│  └────────┘  └───────┘  └────────────┘     │
└─────────────────────────────────────────────┘
         ▲             ▲
    Claude Code     Terminal
```

**Core API** — plain Python module. All business logic lives here. No HTTP, no transport concerns.

**MCP Server** — exposes Core API as MCP tools via `fastmcp`. Claude Code connects to it via `.mcp.json` using `uv run`. Added/removed per project for the on/off toggle.

**CLI** (`timeopt`) — `click` app that calls Core API directly. Works outside Claude. `dump` and `plan` commands call the LLM backend when NLP is needed.

**Slash commands** — markdown prompt templates in `.claude/commands/`. Thin wrappers that instruct Claude to call the appropriate MCP tool. Claude handles NLP; MCP handles persistence.

**Telegram (future extension point)** — the Core API is transport-agnostic by design, making a future Telegram bot a thin client layer like CLI/MCP.

---

## Data Model

### `tasks`
| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID — stable internal key |
| `short_id` | INTEGER | Recycling ID (see below) |
| `display_id` | TEXT | `#42-fix-login-bug` — stored, indexed, human/Claude readable |
| `title` | TEXT | Parsed from brain dump |
| `raw` | TEXT | Original input fragment |
| `priority` | TEXT | `high` / `medium` / `low` |
| `urgent` | BOOLEAN | Whether the task is time-sensitive (independent of priority/importance) |
| `category` | TEXT | `work` / `personal` / `errands` / `other` |
| `effort` | TEXT | `small` / `medium` / `large` (nullable, falls back to `default_effort` config) |
| `due_at` | DATETIME | Nullable, UTC |
| `due_event_uid` | TEXT | CalDAV UID of bound calendar event. Nullable. |
| `due_event_label` | TEXT | Human-readable calendar reference e.g. `"meeting with Jeff"` |
| `due_event_offset_min` | INTEGER | Minutes before (`-`) or after (`+`) the bound event |
| `due_unresolved` | BOOLEAN | True if calendar binding failed — re-attempted on `/sync` |
| `created_at` | DATETIME | UTC |
| `status` | TEXT | `pending` / `delegated` / `done` |
| `done_at` | DATETIME | Nullable, UTC |
| `notes` | TEXT | Append-only log — delegation progress, attempts, failure reasons. Each entry prefixed with UTC timestamp. |

**`short_id` assignment — recycling pool:**
- On task creation: find the lowest free integer in 1–99 not held by any `pending` or `delegated` task
- If all 1–99 are occupied: use `MAX(short_id) + 1` (overflow to 100, 101, …)
- Computed via `SELECT MIN` gap-finding query; not `AUTOINCREMENT`

**`display_id`** is stored (not computed). Uniqueness among active tasks enforced via partial index:
```sql
CREATE UNIQUE INDEX idx_short_id_active ON tasks(short_id) WHERE status IN ('pending', 'delegated');
```
Done tasks retain their historical `display_id` for the log. Lookups always filter to `status IN ('pending', 'delegated')` first.

### Eisenhower Classification

The two Eisenhower axes map to stored columns:
- **Important** → derived from `priority`: `high` or `medium` = important, `low` = not important
- **Urgent** → `urgent` boolean column (set at dump time, inferred by Claude from keywords like "urgent", "before noon", "ASAP")

Quadrant sort order: urgent+important → important-only → urgent-only → neither.

**Auto-classification:** `dump_tasks` and `list_tasks` automatically run Eisenhower classification server-side before returning — Claude never needs to call `classify_tasks` explicitly as part of dump or plan flows.

### `calendar_blocks`
| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID |
| `task_id` | TEXT FK | References `tasks.id` |
| `caldav_uid` | TEXT | UID of the created calendar event |
| `scheduled_at` | DATETIME | Start time of block, UTC |
| `duration_min` | INTEGER | Duration in minutes |
| `plan_date` | DATE | The day this block was planned for |

### `config`
Key-value store. Keys:

| Key | Default | Description |
|---|---|---|
| `day_start` | `09:00` | Work day start time |
| `day_end` | `18:00` | Work day end time |
| `break_duration_min` | `15` | Break duration inserted between blocks |
| `default_effort` | `medium` | Fallback effort when not specified at dump time |
| `effort_small_min` | `30` | Minutes allocated for small tasks |
| `effort_medium_min` | `60` | Minutes allocated for medium tasks |
| `effort_large_min` | `120` | Minutes allocated for large tasks |
| `hide_done_after_days` | `7` | Done tasks older than this are excluded from `list_tasks` by default |
| `fuzzy_match_min_score` | `80` | Minimum rapidfuzz score to act without asking (0–100) |
| `fuzzy_match_ask_gap` | `10` | Ask user if top two scores are within this gap |
| `delegation_max_tool_calls` | `10` | Max tool calls per Delegation Executor before returning to pending |
| `caldav_url` | `https://caldav.yandex.ru` | CalDAV endpoint |
| `caldav_username` | — | Yandex username |
| `caldav_password` | — | App-specific password from Yandex |
| `caldav_read_calendars` | `all` | Comma-separated list of calendar names to read, or `all` |
| `caldav_tasks_calendar` | `Timeopt` | Calendar name to push task blocks into (created if missing) |
| `llm_base_url` | — | OpenAI-compatible base URL (overrides Anthropic default) |
| `llm_api_key` | — | API key for custom LLM backend |
| `llm_model` | `claude-sonnet-4-6` | Model name |

---

## Commands

| Intent | Slash command | CLI |
|---|---|---|
| Brain dump | `/dump fix login, call dentist, prep slides` | `timeopt dump "fix login, call dentist"` |
| View tasks | `/tasks` | `timeopt tasks` |
| Daily plan | `/plan` | `timeopt plan` |
| Mark done | `/done 42-fix-login call dentist` | `timeopt done 42 43` |
| Check urgent | `/check-urgent` | `timeopt check-urgent` |
| Sync calendar refs | `/sync` | `timeopt sync` |
| View history | `/history` | `timeopt history [--today\|--week\|--all]` |
| Config | — | `timeopt config get <key>` / `timeopt config set <key> <value>` |

---

## MCP Tools

**`get_dump_templates(fragments)`**
Accepts a list of raw text fragments (strings). Returns a top-level `schema` key (valid values, annotated once) and a `templates` array — one per fragment with `raw` and `title` populated. Only non-null fields are included in each template; nullable fields with no pre-detected value are omitted entirely.

```json
{
  "schema": {
    "priority": "high|medium|low",
    "urgent": "bool",
    "category": "work|personal|errands|other",
    "effort": "small|medium|large",
    "due_at": "ISO8601 or omit",
    "due_event_label": "string or omit",
    "due_event_offset_min": "int (negative = before event) or omit"
  },
  "templates": [
    { "raw": "fix login bug", "title": "fix login bug", "priority": "?", "urgent": "?", "category": "?", "effort": "?" },
    { "raw": "deploy hotfix before noon", "title": "deploy hotfix before noon", "priority": "?", "urgent": "?", "category": "?", "effort": "?", "due_at": "?" },
    { "raw": "prep report before meeting with Jeff", "title": "prep report before meeting with Jeff", "priority": "?", "urgent": "?", "category": "?", "effort": "?", "due_event_label": "meeting with Jeff", "due_event_offset_min": "?" }
  ]
}
```

**`dump_task(task)`**
Save a single completed task object. Automatically runs Eisenhower classification before saving. Returns `display_id`. Use for one-by-one submission.

**`dump_tasks(tasks)`**
Save a batch of completed task objects. Automatically runs Eisenhower classification before saving. Returns list of `display_id`s.

Note: The Core API exposes `core.dump_tasks(raw_text)` which invokes `LLMClient` internally to parse and save — used by the CLI path.

**`list_tasks(status?, priority?, category?, include_old_done?, fields?)`**
Returns tasks from SQLite. Automatically re-evaluates urgency (due date proximity) before returning. All params optional. Defaults to pending + delegated, non-archived only. Done tasks older than `hide_done_after_days` excluded unless `include_old_done=true`.

By default returns display-only fields: `display_id`, `title`, `priority`, `urgent`, `category`, `effort`, `due_at`, `status`, `notes` (truncated to 60 chars). Full detail available via `get_task(task_id)`.

**`get_task(task_id)`**
Returns full task object for a single task ID. Used when full detail is needed (e.g. to inspect delegation notes, raw fragment, calendar binding fields).

**`fuzzy_match_tasks(query)`**
Runs `rapidfuzz` against active task titles (`status IN ('pending', 'delegated')`). Returns ranked candidates `[{task_id, display_id, title, score}]`.

**Ambiguity resolution rules** (from config):
- `score < fuzzy_match_min_score` → ask user
- `score[0] - score[1] < fuzzy_match_ask_gap` AND `score[0] >= fuzzy_match_min_score` → ask user
- Otherwise → act silently

**`mark_done(task_ids)`**
Accepts a list of task IDs (UUID or `display_id`). Resolves `display_id` by filtering to `status IN ('pending', 'delegated')` only — never matches historical done tasks. Sets `status='done'`, `done_at=now()`.

**`mark_delegated(task_id, notes?)`**
Sets `status='delegated'` and optionally writes initial timestamped note. Called when Claude picks up a Q3 task.

**`update_task_notes(task_id, notes)`**
Validates `task_id` resolves to a `delegated` task — returns error otherwise. Appends a timestamped entry to `notes` (append-only, never overwrites). Format: `[2026-03-27T10:00Z] <content>`.

**`return_to_pending(task_id, notes)`**
Sets `status='pending'`, appends timestamped failure note. Called when Claude cannot complete a delegated task.

**`resolve_calendar_reference(label, date_range?)`**
Runs `rapidfuzz` against calendar event titles for the given date range (default: next 30 days). Returns ranked matches `[{caldav_uid, title, start, end, score}]`. Used during dump to bind textual event references without exposing the full event list to Claude.

**`get_calendar_events(date?, days?)`**
Fetches events from all configured read calendars. Returns `{title, start, end}`. Defaults to today. Read-only. Used for display and planning context — not for fuzzy matching (use `resolve_calendar_reference` instead).

**`get_plan_proposal(date?)`**
Server-side scheduling: fetches calendar events, computes free slots, sorts pending tasks by Eisenhower quadrant, assigns tasks to slots using config effort sizes, inserts breaks, defers overflow. Returns a ready-made `[{task_id, display_id, title, start, duration_min, quadrant}]` block list. Claude receives a finished proposal to display and confirm — no scheduling reasoning required.

**`push_calendar_blocks(blocks, date?)`**
Transactional: all CalDAV writes are collected first, then SQLite is committed only on full success. If CalDAV is unreachable, the operation aborts and the previous plan is preserved unchanged.
1. Attempt all CalDAV event creations, collect `caldav_uid`s
2. On full success: delete old `calendar_blocks` rows for `plan_date`, delete old CalDAV events, insert new rows
3. On any failure: abort, return error — no partial state

**`classify_tasks(task_ids?)`**
Explicit Eisenhower classification for `/check-urgent`. Considers `priority`, `urgent`, and due date proximity. Persists updated urgency to DB. Returns quadrant assignments. (Note: dump and list flows run this automatically — explicit calls only needed for check-urgent.)

**`get_config(key?)`** / **`set_config(key, value)`**
Read/write config table.

---

## Eisenhower Matrix & Delegation

The two stored axes:
- **Important** — derived from `priority`: `high` or `medium` = important, `low` = not important
- **Urgent** — `urgent` boolean, set at dump time from keywords ("urgent", "ASAP", "before noon"). Auto-upgraded if `due_at` is today or overdue.

**Quadrant behaviour:**

| Quadrant | Condition | Planner action |
|---|---|---|
| Q1 | urgent + important | Schedule first |
| Q2 | important, not urgent | Schedule after Q1 |
| Q3 | urgent, not important | Delegate to Claude |
| Q4 | not urgent, not important | Schedule last |

**Q3 delegation flow:**
1. Q3 task is detected during `/dump`, `/plan`, or `/check-urgent`
2. Claude calls `mark_delegated(task_id)` and creates a Claude `TaskCreate` todo: *"Delegate: [task title]"*
3. Delegation Executor subagent spins up — budget: `delegation_max_tool_calls` tool calls max
4. On success: calls `mark_done(task_id)`, writes summary via `update_task_notes`
5. On budget exceeded or failure: calls `return_to_pending(task_id, notes)` — task reappears in user's queue with notes visible

**`/tasks` display** shows delegated tasks in a dedicated section:
```
Pending (3)        Being handled by Claude (2)
#1-fix-login-bug   #3-reply-to-dentist     [delegated, trying: sending email...]
#2-call-dentist    #7-book-flight          [delegated, failed: no calendar access]
#4-prep-slides
```

**`/check-urgent`** calls `classify_tasks` (MCP tool), identifies Q3 tasks not yet delegated, dispatches Delegation Executors in parallel via main Claude.

---

## User Stories

> **Testing note:** Each user story below must have a corresponding end-to-end test driven by the Playwright MCP. Tests type commands into the Claude Code TUI, wait for responses, and assert on visible output (task IDs, status labels, schedule blocks, etc.).

---

## User Story: Brain Dump

**Input:**
```
/dump fix login bug, call dentist, urgent: deploy hotfix before noon, prep slides for thursday
```

**Step 1 — Split**
Claude identifies fragment boundaries (commas, semicolons, newlines, "and also", etc.) and produces:
```
["fix login bug", "call dentist", "urgent: deploy hotfix before noon", "prep slides for thursday"]
```

**Step 2 — Get templates**
Claude calls `get_dump_templates(fragments)`. Server returns schema once + sparse templates (only non-null fields included):
```json
{
  "schema": { "priority": "high|medium|low", "urgent": "bool", "category": "work|personal|errands|other", "effort": "small|medium|large", "due_at": "ISO8601 or omit" },
  "templates": [
    { "raw": "fix login bug",                    "title": "fix login bug",             "priority": "?", "urgent": "?", "category": "?", "effort": "?" },
    { "raw": "call dentist",                      "title": "call dentist",              "priority": "?", "urgent": "?", "category": "?", "effort": "?" },
    { "raw": "urgent: deploy hotfix before noon", "title": "deploy hotfix before noon", "priority": "?", "urgent": "?", "category": "?", "effort": "?", "due_at": "?" },
    { "raw": "prep slides for thursday",          "title": "prep slides for thursday",  "priority": "?", "urgent": "?", "category": "?", "effort": "?", "due_at": "?" }
  ]
}
```

**Step 3 — Fill templates**
Claude fills each template iteratively:
```json
[
  { "raw": "fix login bug",                    "title": "fix login bug",             "priority": "high",   "urgent": false, "category": "work",     "effort": "medium" },
  { "raw": "call dentist",                      "title": "call dentist",              "priority": "medium", "urgent": false, "category": "personal", "effort": "small"  },
  { "raw": "urgent: deploy hotfix before noon", "title": "deploy hotfix before noon", "priority": "high",   "urgent": true,  "category": "work",     "effort": "medium", "due_at": "<today>T12:00:00" },
  { "raw": "prep slides for thursday",          "title": "prep slides for thursday",  "priority": "high",   "urgent": false, "category": "work",     "effort": "large",  "due_at": "<thursday>T18:00:00" }
]
```

**Step 4 — Save**
Claude submits individually (`dump_task`) or as batch (`dump_tasks`). Server auto-runs Eisenhower classification on save.

**Step 5 — Summary (from server)**
```
Added 4 tasks:
  #1-fix-login-bug             [work, high]
  #2-call-dentist              [personal, medium]
  #3-deploy-hotfix-before-noon [work, high, urgent, due today 12:00]
  #4-prep-slides-for-thursday  [work, high, due Thu]
```

---

## User Story: View Tasks

**Input:**
```
/tasks
```

**Expected output:**
```
Pending (4)
  #1-fix-login-bug             [work, high]
  #4-prep-slides-for-thursday  [work, high, due Thu]
  #2-call-dentist              [personal, medium]
  #5-buy-groceries             [errands, low]

Being handled by Claude (1)
  #3-deploy-hotfix-before-noon [work, high, urgent — trying: pushing to staging...]
```

Tasks sorted by Eisenhower quadrant then priority. Delegated tasks shown separately with latest `notes` inline.

**Playwright assertion:** output contains all `display_id`s, delegated section is visible, sort order is correct.

---

## User Story: Mark Done

**Input:**
```
/done fix login prep slides
```

**Step 1 — Fuzzy match**
Claude calls `fuzzy_match_tasks("fix login")` → `[{#1-fix-login-bug, score: 95}]` — above threshold, act silently.
Claude calls `fuzzy_match_tasks("prep slides")` → `[{#4-prep-slides-for-thursday, score: 91}]` — above threshold, act silently.

**Step 2 — Mark done**
Claude calls `mark_done(["<id-1>", "<id-4>"])`.

**Step 3 — Confirm**
```
Done:
  ✓ #1-fix-login-bug
  ✓ #4-prep-slides-for-thursday
```

**Edge case — ambiguous match:**
`/done login` → `fuzzy_match_tasks` returns `#1-fix-login-bug (score: 88)` and `#8-fix-login-redirect (score: 82)`. Gap = 6 < `fuzzy_match_ask_gap` (10) → Claude uses `AskUserQuestion` to confirm.

**Playwright assertion:** marked tasks disappear from `/tasks` output, confirmation message visible.

---

## User Story: Daily Plan

**Input:**
```
/plan
```

**Step 1 — Get proposal**
Daily Planner subagent calls `get_plan_proposal(today)`. Server fetches calendar, computes free slots, sorts tasks, assigns blocks, inserts breaks:
```
Proposal:
  10:00–11:00  #3-deploy-hotfix   [Q1, medium]
  11:15–12:15  #1-fix-login-bug   [Q2, medium]
  12:30–14:00  #4-prep-slides     [Q2, large]
  15:30–16:00  #2-call-dentist    [Q4, small]
  Deferred: none
```

**Step 2 — Push & display**
Calls `push_calendar_blocks(proposal)` using transactional semantics. Displays schedule.

**Playwright assertion:** schedule visible in TUI, all tasks assigned, Timeopt calendar events created.

---

## User Story: Check Urgent & Delegation

**Input:**
```
/check-urgent
```

**Step 1 — Classify**
Main Claude calls `classify_tasks()`. Returns `#6-reply-to-accountant` as Q3 (urgent + not important).

**Step 2 — Delegate**
Main Claude calls `mark_delegated("#6-reply-to-accountant")`, creates Claude todo: *"Delegate: reply to accountant"*.
Dispatches Delegation Executor subagent (budget: `delegation_max_tool_calls`).
Executor calls `update_task_notes` as it progresses.
On success: `mark_done("#6-...")`.

**Step 3 — Report**
```
Delegated 1 task:
  #6-reply-to-accountant → Claude is handling it
```

**Failure path:**
Executor cannot send email → calls `return_to_pending("#6-...", "No email tool available")`.
```
Could not delegate:
  #6-reply-to-accountant → returned to your queue (no email tool available)
```

**Playwright assertion:** task status changes to `delegated` then `done` (or back to `pending` on failure), notes visible in `/tasks`.

---

## Slash Command Prompts

Each command in `.claude/commands/` is a markdown prompt template instructing Claude to call the relevant MCP tool(s) and act decisively. Claude defaults to sensible decisions and only uses `AskUserQuestion` when the fuzzy match threshold rules require it.

**Decision defaults:**

| Situation | Default behavior |
|---|---|
| `/done` match above threshold, gap large enough | Act silently, report |
| `/done` match below threshold or gap too small | `AskUserQuestion` |
| Effort not specified | Use `default_effort` from config |
| Overloaded day | Defer lowest-priority tasks automatically, report what was deferred |
| Category unclear | Best guess from context, no confirmation |

---

## Daily Planner Logic

Main Claude dispatches Daily Planner subagent, which:

1. Calls `get_plan_proposal(date?)` — server computes full schedule (free slots, Eisenhower sort, effort mapping, breaks, overflow deferral)
2. Calls `push_calendar_blocks(proposal)` — transactional push to CalDAV + SQLite
3. Returns formatted schedule to main Claude for display

Claude does not perform scheduling reasoning — the server handles it entirely.

---

## LLM Client

A thin abstraction layer used by the CLI (and Core API `dump_tasks`) when called outside Claude:

```python
class LLMClient:
    def complete(self, system: str, user: str) -> str: ...
```

Implementations:
- `AnthropicClient` — default, uses `ANTHROPIC_API_KEY`
- `OpenAICompatibleClient` — uses `llm_base_url` + `llm_api_key` + `llm_model` from config

If `ANTHROPIC_API_KEY` is unset and no custom backend is configured, CLI exits with a clear error pointing to the config keys.

---

## CalDAV Integration

- Library: `caldav` (Python)
- Auth: app-specific password from Yandex (not main account password)
- **Read calendars**: configurable list (default: all). Used to compute free/busy time. Read-only — user calendars are never modified.
- **Write calendar**: dedicated `Timeopt` calendar. Auto-created on first push if it doesn't exist.
- **Re-plan behavior**: `push_calendar_blocks` uses transactional semantics — CalDAV writes collected first, SQLite committed only on full success. Previous plan preserved on failure.
- **Sync token**: used opportunistically to detect changed events. If Yandex CalDAV does not return a sync token (RFC 6578 not guaranteed), falls back to re-fetching events for the relevant date window and comparing against stored `due_at` values.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| CalDAV unreachable | Warn user, plan proceeds without calendar data |
| `/done` match below `fuzzy_match_min_score` | `AskUserQuestion` to confirm |
| `/done` top two scores within `fuzzy_match_ask_gap` | `AskUserQuestion` to confirm |
| Overloaded day | Defer lowest-priority tasks automatically, report what was deferred |
| `ANTHROPIC_API_KEY` unset (CLI) | Exit with clear error pointing to config keys |
| SQLite read error | Log exception, surface error to user — no silent failures |
| `push_calendar_blocks` CalDAV failure | Abort transaction, previous plan preserved, error reported |
| Delegation budget exceeded | `return_to_pending` with "Exceeded delegation budget" note |
| `update_task_notes` on non-delegated task | Return error — no write performed |

SQLite runs in WAL mode for crash safety.

---

## On/Off Toggle

The plugin is MCP-based and project-scoped:
- **On**: add server entry to `.mcp.json` in the project root
- **Off**: remove it — zero context overhead in unrelated projects

Slash commands in `.claude/commands/` should also be scoped to projects where the plugin is active.

---

## Testing

- **Unit tests** (`pytest`) — Core API: `get_plan_proposal` scheduling, `short_id` recycling, `hide_done_after_days` filtering, Eisenhower auto-classification, fuzzy threshold logic
- **Integration tests** — SQLite round-trips: create, list, mark done, delegated lifecycle, config read/write
- **CalDAV mocked** — `caldav` client stubbed in tests; manual test script for live Yandex Calendar verification
- **MCP tool tests** — each tool called directly against in-memory SQLite DB
- **CLI tests** — `click` test runner for `tasks`, `done`, `history`, `config`; `dump` and `plan` with mocked `LLMClient`
- **E2E tests** — Playwright MCP drives Claude Code TUI for each user story

---

## Repo Layout

```
timeopt/
├── .claude-plugin/
│   └── plugin.json          # name, description, version
├── .mcp.json                # MCP server config (uv run timeopt-server)
├── .claude/
│   └── commands/            # Slash command markdown templates
│       ├── dump.md
│       ├── tasks.md
│       ├── plan.md
│       ├── done.md
│       ├── check-urgent.md
│       ├── sync.md
│       └── history.md
├── src/
│   └── timeopt/
│       ├── core.py          # Core API — all business logic
│       ├── db.py            # SQLite layer
│       ├── caldav_client.py # CalDAV integration
│       ├── planner.py       # Scheduling + Eisenhower classification
│       ├── llm_client.py    # LLM abstraction (Anthropic / OpenAI-compatible)
│       ├── server.py        # MCP server (fastmcp)
│       └── cli.py           # click CLI entry point
├── tests/
├── docs/
│   └── superpowers/specs/
├── pyproject.toml           # uv project — defines timeopt and timeopt-server scripts
├── .gitignore
└── README.md
```

**Dependency management:** `uv` (pure PyPI).
**Key dependencies:** `fastmcp`, `caldav`, `click`, `anthropic`, `openai`, `rapidfuzz`.

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

---

## Subagents

**Constraint:** subagents cannot dispatch other subagents. Main Claude is always the orchestrator — subagents are leaf workers that only call MCP tools.

**Eisenhower Classifier — Core API function, not a subagent**
Deterministic server-side function. Runs automatically inside `dump_tasks` and `list_tasks`. Exposed as `classify_tasks` MCP tool for explicit use by `/check-urgent` only.

**Brain Dump Parser** _(leaf subagent)_
Dispatched by main Claude on `/dump`. Splits raw text → calls `get_dump_templates` → fills each template iteratively → saves via `dump_task` / `dump_tasks` → returns summary. No sub-dispatching.

**Daily Planner** _(leaf subagent)_
Dispatched by main Claude on `/plan`. Calls `get_plan_proposal` → calls `push_calendar_blocks` → returns formatted schedule. Three tool calls total — no scheduling reasoning.

**Delegation Executor** _(leaf subagent, one per Q3 task)_
Dispatched by **main Claude** only. Budget: `delegation_max_tool_calls` tool calls. Attempts task using available tools. Writes progress via `update_task_notes`. On success: `mark_done`. On budget exceeded or failure: `return_to_pending`.

**Orchestration summary:**
```
Main Claude
├── /dump         → dispatches Brain Dump Parser (leaf)
├── /plan         → dispatches Daily Planner (leaf)
├── /check-urgent → calls classify_tasks (MCP tool)
│                   dispatches Delegation Executors in parallel (leaves)
└── /sync         → algorithmic (no subagent) + Claude-inline for unresolved tasks
```

---

## Calendar Event Binding

Tasks with due dates derived from calendar references (e.g. "before meeting with Jeff") are bound to a specific CalDAV event at dump time.

### Data model
See `tasks` table: `due_event_uid`, `due_event_label`, `due_event_offset_min`, `due_unresolved`.

### Binding at dump time

1. Server pre-detects textual calendar references in fragments and includes `due_event_label` in the template
2. Claude fills `due_event_offset_min` (e.g. `-30` for "30 min before")
3. Server calls `resolve_calendar_reference(label)` internally on save:
   - **Clear match** — store `due_event_uid`, compute `due_at`, set `due_unresolved=false`
   - **Multiple close matches** — pick highest score, proceed silently
   - **No match** — event reference understood but not in calendar yet:
     1. Claude estimates `due_at` from context and world knowledge. Sets provisionally, `due_unresolved=true`
     2. If estimate fails → `AskUserQuestion`: "Couldn't find this event — when do you expect it?" with Skip option
     3. If skipped → no `due_at`, `due_unresolved=true`
   - `due_event_label` always stored regardless

### `/sync` command

**1. Algorithmic sync (no Claude)** — bound tasks (`due_event_uid IS NOT NULL`):
- Fetches CalDAV sync token if available (RFC 6578); falls back to full re-fetch + comparison if not supported
- Recomputes `due_at` for tasks referencing changed events
- Reports changes:
  ```
  Updated 2 task due dates:
    #5-prepare-report   Wed 14:00 → Thu 10:00  (meeting with Jeff rescheduled)
    #8-send-invoice     Wed 14:00 → Thu 10:00
  ```

**2. Claude-triggered sync** — unresolved tasks (`due_unresolved=true`) only:
- Re-attempts binding via `resolve_calendar_reference`
- If still no match: Claude re-estimates or asks user
- Once resolved: clears `due_unresolved`, stores `due_event_uid`

Tasks with directly specified due dates (`due_event_uid IS NULL`, `due_unresolved=false`) are **never touched** by `/sync`.

**If the bound event is deleted:** task keeps last `due_at`, Claude warns: *"#5-prepare-report due date may be stale — 'meeting with Jeff' was removed from calendar"*.

---

## Future Extension Points

- **Telegram bot** — thin client layer on Core API, same tools as CLI (brain dump, task list, plan, mark done, free slot queries)
- **Recurring tasks** — add `recurrence` field to `tasks` table
- **Multi-user** — Core API is stateless by design; SQLite path could be parameterized per user
- **Push notifications** — CalDAV subscription or polling for meeting reminders
