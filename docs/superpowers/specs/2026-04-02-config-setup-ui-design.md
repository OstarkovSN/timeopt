# Config Cleanup, Setup Interface & Web UI

**Date:** 2026-04-02
**Status:** Approved

---

## Overview

Three related improvements:

1. **Config cleanup** — move hardcoded fallback values out of `server.py` and `llm_client.py` into `_CONFIG_DEFAULTS` in `core.py`
2. **Setup interface** — tiered setup via both a `/timeopt:setup` slash command and `timeopt setup` CLI command
3. **Web UI** — optional local FastAPI + HTMX + Jinja2 web interface, starting with a config page, designed to grow

---

## Part 1: Config Cleanup

### New config keys to add to `_CONFIG_DEFAULTS`

| Key | Default | Currently |
|---|---|---|
| `caldav_url` | `"https://caldav.yandex.ru"` | hardcoded fallback in `server.py:38` |
| `caldav_read_calendars` | `"all"` | hardcoded fallback in `server.py:41` |
| `caldav_tasks_calendar` | `"Timeopt"` | hardcoded fallback in `server.py:42` |
| `llm_max_tokens` | `"4096"` | hardcoded in `llm_client.py:39` |
| `calendar_fuzzy_min_score` | `"50"` | hardcoded in `core.py:393` |
| `ui_port` | `"7749"` | new — web UI port |

Move `caldav_url`, `caldav_read_calendars`, `caldav_tasks_calendar` from `_CONFIG_OPTIONAL` to `_CONFIG_DEFAULTS` (they have sensible defaults; no reason to be optional).

### Changes per file

**`core.py`:**
- Add the 6 keys above to `_CONFIG_DEFAULTS`
- Move `caldav_url`, `caldav_read_calendars`, `caldav_tasks_calendar` out of `_CONFIG_OPTIONAL`
- In `resolve_calendar_reference`: accept `min_score` param (default read from config at call site), replace hardcoded `50`

**`server.py` `_get_caldav()`:**
- Remove inline fallback strings; read from config (they now have defaults)

**`llm_client.py` `AnthropicClient.complete()`:**
- Accept `max_tokens` param; callers pass `int(config["llm_max_tokens"])`
- `build_llm_client` passes it through

---

## Part 2: Setup Interface

### Flow (both interfaces share this logic)

**Step 1 — LLM (required to use `/timeopt:dump`)**
```
Provider?
  1. Anthropic  → ask: api_key, model (default: claude-sonnet-4-6)
  2. OpenAI     → set llm_base_url="https://api.openai.com/v1", ask: api_key, model (default: gpt-4o)
  3. Custom     → ask: base_url, api_key, model
  4. Skip
```

**Step 2 — CalDAV (optional)**
```
Configure Yandex Calendar / CalDAV? [y/N]
  → ask: url (default shown), username, password
  → optionally: read_calendars, tasks_calendar
```

**Step 3 — Scheduling defaults (optional)**
```
Customize scheduling defaults? [y/N]
  → day_start (default: 09:00)
  → day_end (default: 18:00)
  → break_duration_min (default: 15)
  → default_effort (default: medium)
  → effort_small_min / effort_medium_min / effort_large_min
```

**Step 4 — Web UI**
```
Open web UI? [y/N]  → if yes, start ui server + open browser
```

### `/timeopt:setup` slash command (`commands/setup.md`)

Instructs Claude to:
1. Call `get_config` (no key) to see current state
2. Tell the user what's configured and what's missing
3. Walk through steps 1–4 above using `set_config` after each answer
4. If "open web UI": call CLI or note that `timeopt ui` starts it

### `timeopt setup` CLI command (`cli.py`)

New `click` command `setup`:
- Shows current config state at the start ("LLM: configured / CalDAV: not set")
- Uses `click.prompt` with current config values as defaults (so re-running setup is non-destructive)
- Uses `click.confirm` for optional sections
- Calls `core.set_config` for each value
- Offers to launch `timeopt ui` at the end

---

## Part 3: Web UI

### Stack

- **Backend:** FastAPI app in `src/timeopt/ui_server.py`
- **Templates:** Jinja2, stored in `src/timeopt/templates/`
- **Frontend:** HTMX (CDN) + minimal CSS — no build step
- **Port:** configurable via `ui_port` config key (default `7749`)

### Layout

```
┌─────────────────────────────────────────┐
│  timeopt                           [nav] │
├──────────┬──────────────────────────────┤
│ Sidebar  │  Main content area           │
│          │                              │
│ > Config │  (active page renders here)  │
│   Tasks  │                              │
│   Plan   │                              │
│          │                              │
└──────────┴──────────────────────────────┘
```

Sidebar nav items link to HTMX-loaded partials in the main area. Adding a new page = new nav entry + new template partial + new FastAPI route.

### Config page (first page)

Groups config keys into sections:

- **LLM** — provider selector (Anthropic / OpenAI / Custom), api_key (masked), model, max_tokens
- **CalDAV** — url, username, password (masked), read_calendars, tasks_calendar
- **Scheduling** — day_start, day_end, break_duration_min, default_effort, effort sizes
- **Behavior** — hide_done_after_days, fuzzy_match thresholds

Each field: inline edit → HTMX POST to `/api/config` → success/error feedback in place. No full-page reload.

### FastAPI routes

```
GET  /                    → redirect to /config
GET  /config              → full page (base template + config partial)
GET  /partials/config     → config partial only (HTMX target)
POST /api/config          → set one key/value, returns feedback snippet
GET  /api/config          → all config as JSON (for JS init)
```

Future pages add their own `GET /page` + `GET /partials/page` + any API routes.

### File layout

```
src/timeopt/
  ui_server.py          ← FastAPI app, routes
  templates/
    base.html           ← sidebar, nav, HTMX CDN
    config.html         ← full config page
    partials/
      config.html       ← config form partial (HTMX target)
      config_field.html ← single field row (success/error feedback)
```

### CLI command

`timeopt ui` (new click command):
- Reads `ui_port` from config
- Starts FastAPI via `uvicorn` (subprocess or in-process)
- Opens browser to `http://localhost:{port}`
- Logs the URL

### Dependencies to add

- `fastapi`
- `uvicorn`
- `jinja2`
- `python-multipart` (FastAPI form parsing)

---

## Testing

- Config cleanup: update existing tests that check config defaults; add tests for new keys
- Setup CLI: test with `CliRunner`, mock `core.set_config`, assert correct keys written per provider choice
- Web UI: one integration test per route (FastAPI `TestClient`) asserting status 200 and key content; test `POST /api/config` saves correctly and returns feedback

---

## Out of scope

- Authentication for the web UI (local tool, no auth needed)
- Tasks and Plan pages (future)
- Hot-reload of config in running MCP server
