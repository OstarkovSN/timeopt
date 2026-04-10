# timeopt

A Claude Code plugin for personal task management with Eisenhower Matrix prioritization and Yandex Calendar integration.

Brain-dump tasks in plain text, get a time-blocked daily schedule, and push it back to your calendar.

## Installation

```
/plugin install <repo-url>
```

The MCP server starts automatically via `uv run timeopt-server`. No manual setup needed beyond configuration.

## Setup

The fastest way to configure timeopt is the interactive setup wizard:

```bash
timeopt setup
```

It walks through:
1. **LLM provider** — Anthropic, OpenAI, or any OpenAI-compatible endpoint
2. **CalDAV** — Yandex Calendar or any CalDAV server (optional)
3. **Scheduling defaults** — work hours, breaks, effort sizes (optional)

Alternatively, use the `/timeopt:setup` slash command to run the same wizard from inside Claude Code.

## Web UI

A local config editor is available at `http://localhost:7749`:

```bash
timeopt ui
```

All config keys are editable inline — changes save on field blur with no page reload.

## Configuration

Fine-tune individual values with `timeopt config set <key> <value>` or via the web UI.

| Key | Default | Description |
|---|---|---|
| `day_start` | `09:00` | Work day start (HH:MM) |
| `day_end` | `18:00` | Work day end (HH:MM) |
| `break_duration_min` | `15` | Break between scheduled blocks (minutes) |
| `default_effort` | `medium` | Default task effort when unspecified |
| `effort_small_min` | `30` | Minutes for "small" effort tasks |
| `effort_medium_min` | `60` | Minutes for "medium" effort tasks |
| `effort_large_min` | `120` | Minutes for "large" effort tasks |
| `ui_port` | `7749` | Port for `timeopt ui` |

### LLM

| Key | Default | Description |
|---|---|---|
| `llm_api_key` | — | API key (or set `ANTHROPIC_API_KEY` env var) |
| `llm_model` | — | Model name (e.g. `claude-sonnet-4-6`, `gpt-4o`) |
| `llm_base_url` | — | Base URL for OpenAI-compatible endpoints; omit for Anthropic |
| `llm_max_tokens` | `4096` | Max tokens per LLM completion |

### CalDAV (optional)

| Key | Default | Description |
|---|---|---|
| `caldav_url` | `https://caldav.yandex.ru` | CalDAV server URL |
| `caldav_username` | — | CalDAV username |
| `caldav_password` | — | CalDAV password |
| `caldav_read_calendars` | `all` | Calendars to read events from |
| `caldav_tasks_calendar` | `Timeopt` | Calendar to push scheduled blocks into |

For Yandex Calendar, get an app-specific password at [Yandex ID security settings](https://id.yandex.ru/security).

## Slash Commands

| Command | Description |
|---|---|
| `/timeopt:dump` | Brain-dump tasks in free-form text |
| `/timeopt:tasks` | View all pending tasks |
| `/timeopt:plan` | Generate a time-blocked schedule for today |
| `/timeopt:done` | Mark a task as completed (fuzzy search) |
| `/timeopt:sync` | Sync CalDAV events with bound tasks |
| `/timeopt:history` | View recently completed tasks |
| `/timeopt:check-urgent` | List tasks that need attention today |
| `/timeopt:setup` | Interactive setup wizard |

## CLI

The `timeopt` CLI is also available for scripting:

```bash
timeopt dump "fix login bug, call dentist, prep slides for thursday"
timeopt tasks
timeopt plan
timeopt done "login bug"
timeopt config get day_start
timeopt config set day_start 08:00
timeopt setup       # interactive setup wizard
timeopt ui          # open web config editor
```

## Storage

Tasks are stored in `~/.timeopt/tasks.db` (SQLite). Override with `TIMEOPT_DB` environment variable.
