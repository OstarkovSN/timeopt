# timeopt — Context for Claude

Personal task manager Claude Code plugin. Eisenhower Matrix prioritization + optional Yandex Calendar (CalDAV) integration.

## Commands

```bash
uv run pytest tests/ -v          # run all tests
uv run timeopt-server             # start MCP server (stdio transport)
uv run timeopt tasks              # CLI
TIMEOPT_DB=/tmp/test.db uv run timeopt tasks  # use isolated DB
```

## Project Layout

- `src/timeopt/db.py` — SQLite schema, connection helpers
- `src/timeopt/core.py` — task CRUD, config, LLM dump pipeline
- `src/timeopt/planner.py` — Eisenhower classification, scheduling, CalDAV push
- `src/timeopt/caldav_client.py` — CalDAVClient wrapper
- `src/timeopt/llm_client.py` — AnthropicClient / OpenAICompatibleClient
- `src/timeopt/server.py` — FastMCP server (19 tools)
- `src/timeopt/cli.py` — click CLI
- `commands/` — slash command markdown files (`/timeopt:dump` etc.)

## Available Tools (MCP)

- `dump_task` / `dump_tasks` — save tasks from structured input
- `get_dump_templates` — LLM-fillable templates for raw text fragments
- `list_tasks` — pending/delegated/done tasks
- `get_task` — single task by UUID
- `fuzzy_match_tasks` — approximate title match → UUID + score
- `mark_done` / `mark_delegated` — status transitions (accept UUID or display_id)
- `update_task_notes` — append note to delegated task (UUID only)
- `return_to_pending` — delegated → pending (UUID only)
- `classify_tasks` — Eisenhower sort Q1→Q4
- `get_plan_proposal` — time-blocked schedule for a date
- `push_calendar_blocks` — push plan to Yandex Calendar
- `get_calendar_events` — fetch CalDAV events
- `resolve_calendar_reference` — fuzzy-match text → calendar event
- `sync_calendar` — sync bound tasks against latest events
- `get_config` / `set_config` — read/write config

## Key Concepts

**Eisenhower quadrants:** Q1 = urgent+important, Q2 = important not urgent, Q3 = urgent not important, Q4 = neither. "Important" means priority is `high` or `medium`.

**Effort sizes:** small=30min, medium=60min, large=120min (all configurable). Default effort is `medium`.

**Task identity:** `mark_done` and `mark_delegated` accept display IDs (e.g. `#3-fix-login`) or UUIDs. `get_task`, `update_task_notes`, `return_to_pending` require UUID — use `fuzzy_match_tasks` first.

**CalDAV is optional.** All tools degrade gracefully when CalDAV is not configured — return warnings/empty lists, never errors. Planning works with an empty events list.

**DB path:** defaults to `~/.timeopt/tasks.db`. Override with `TIMEOPT_DB` env var.

## Slash Commands

`/timeopt:dump`, `/timeopt:tasks`, `/timeopt:plan`, `/timeopt:done`, `/timeopt:sync`, `/timeopt:history`, `/timeopt:check-urgent`
