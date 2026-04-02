# Config Cleanup, Setup Interface & Web UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move hardcoded values into config, add a tiered setup wizard (CLI + slash command), and ship a FastAPI/HTMX/Jinja2 web UI starting with a config page.

**Architecture:** Config cleanup makes all tunable values accessible via `core.get_config`; the setup wizard (both CLI and slash-command forms) walks through LLM → CalDAV → scheduling defaults → web UI offer; the web UI is a FastAPI app with Jinja2 templates and HTMX for inline field saves, designed to grow by adding nav entries and template partials.

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, Jinja2, HTMX 1.9 (CDN), Click, pytest, FastAPI TestClient.

---

## File Map

| Action | File | Purpose |
|---|---|---|
| Modify | `src/timeopt/core.py` | Add 6 new config keys; move 3 caldav keys from optional→defaults; add `min_score` param to `resolve_calendar_reference`; read `calendar_fuzzy_min_score` in `try_resolve_unresolved` |
| Modify | `src/timeopt/server.py` | Remove inline fallbacks in `_get_caldav()`; pass `min_score` when calling `core.resolve_calendar_reference` |
| Modify | `src/timeopt/cli.py` | Remove inline fallbacks in `_get_caldav_client()`; add `setup` command; add `ui` command |
| Modify | `src/timeopt/llm_client.py` | Add `max_tokens` param to `AnthropicClient.__init__` and `complete`; pass it in `build_llm_client` |
| Create | `src/timeopt/ui_server.py` | FastAPI app with config routes |
| Create | `src/timeopt/templates/base.html` | Sidebar layout, HTMX CDN |
| Create | `src/timeopt/templates/config.html` | Full config page (extends base) |
| Create | `src/timeopt/templates/partials/config.html` | Config form partial (HTMX target) |
| Create | `src/timeopt/templates/partials/config_field.html` | Single field row (returned on POST /api/config/{key}) |
| Create | `commands/setup.md` | `/timeopt:setup` slash command |
| Modify | `pyproject.toml` | Add fastapi, uvicorn, jinja2, python-multipart |
| Modify | `tests/test_core.py` | Add new default keys to `DEFAULTS` dict |
| Modify | `tests/test_llm.py` | Add test for `max_tokens` forwarding |
| Create | `tests/test_ui_server.py` | FastAPI route tests via TestClient |

---

## Task 1: Extend `_CONFIG_DEFAULTS` in `core.py`

**Files:**
- Modify: `src/timeopt/core.py:13-32`
- Modify: `tests/test_core.py:1-16`

- [ ] **Step 1: Write failing test for new default keys**

```python
# tests/test_core.py — update DEFAULTS dict (lines 4-16) and add one new test

DEFAULTS = {
    "day_start": "09:00",
    "day_end": "18:00",
    "break_duration_min": "15",
    "default_effort": "medium",
    "effort_small_min": "30",
    "effort_medium_min": "60",
    "effort_large_min": "120",
    "hide_done_after_days": "7",
    "fuzzy_match_min_score": "80",
    "fuzzy_match_ask_gap": "10",
    "delegation_max_tool_calls": "10",
    # New keys:
    "caldav_url": "https://caldav.yandex.ru",
    "caldav_read_calendars": "all",
    "caldav_tasks_calendar": "Timeopt",
    "llm_max_tokens": "4096",
    "calendar_fuzzy_min_score": "50",
    "ui_port": "7749",
}


def test_new_config_defaults(conn):
    from timeopt.core import get_config
    assert get_config(conn, "caldav_url") == "https://caldav.yandex.ru"
    assert get_config(conn, "caldav_read_calendars") == "all"
    assert get_config(conn, "caldav_tasks_calendar") == "Timeopt"
    assert get_config(conn, "llm_max_tokens") == "4096"
    assert get_config(conn, "calendar_fuzzy_min_score") == "50"
    assert get_config(conn, "ui_port") == "7749"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
uv run pytest tests/test_core.py::test_new_config_defaults -v
```
Expected: `FAILED` — `KeyError: 'Unknown config key: caldav_url'`

- [ ] **Step 3: Update `_CONFIG_DEFAULTS` and `_CONFIG_OPTIONAL` in `core.py`**

Replace `_CONFIG_DEFAULTS` and `_CONFIG_OPTIONAL` (lines 13–32):

```python
_CONFIG_DEFAULTS: dict[str, str] = {
    "day_start": "09:00",
    "day_end": "18:00",
    "break_duration_min": "15",
    "default_effort": "medium",
    "effort_small_min": "30",
    "effort_medium_min": "60",
    "effort_large_min": "120",
    "hide_done_after_days": "7",
    "fuzzy_match_min_score": "80",
    "fuzzy_match_ask_gap": "10",
    "delegation_max_tool_calls": "10",
    "caldav_url": "https://caldav.yandex.ru",
    "caldav_read_calendars": "all",
    "caldav_tasks_calendar": "Timeopt",
    "llm_max_tokens": "4096",
    "calendar_fuzzy_min_score": "50",
    "ui_port": "7749",
}

# Optional keys — no default, return None if unset
_CONFIG_OPTIONAL: frozenset[str] = frozenset({
    "caldav_username", "caldav_password",
    "llm_base_url", "llm_api_key", "llm_model",
})
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
uv run pytest tests/test_core.py -v
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/core.py tests/test_core.py
git commit -m "feat(config): add caldav/llm/ui defaults; move caldav keys from optional"
```

---

## Task 2: Remove inline fallbacks from `server.py` and `cli.py`

**Files:**
- Modify: `src/timeopt/server.py:37-48`
- Modify: `src/timeopt/cli.py:40-50`

- [ ] **Step 1: Write failing test for server `_get_caldav` using config**

```python
# tests/test_server.py — add at the bottom

def test_get_caldav_uses_config_defaults(server_env):
    """_get_caldav() reads url/calendars from config, not inline fallbacks."""
    from timeopt import db, core
    conn = db.get_connection(server_env)
    core.set_config(conn, "caldav_url", "https://custom.caldav.example.com")
    core.set_config(conn, "caldav_username", "user")
    core.set_config(conn, "caldav_password", "pass")
    conn.close()

    with patch("timeopt.server.CalDAVClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        from timeopt.server import _get_caldav, _open_conn
        c = _open_conn()
        _get_caldav(c)
        c.close()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["url"] == "https://custom.caldav.example.com"
```

- [ ] **Step 2: Run test to confirm it fails or passes already**

```bash
uv run pytest tests/test_server.py::test_get_caldav_uses_config_defaults -v
```

- [ ] **Step 3: Fix `server.py` `_get_caldav()`**

Replace lines 37–48 in `src/timeopt/server.py`:

```python
def _get_caldav(conn) -> Optional[CalDAVClient]:
    url = core.get_config(conn, "caldav_url")
    username = core.get_config(conn, "caldav_username")
    password = core.get_config(conn, "caldav_password")
    read_cals = core.get_config(conn, "caldav_read_calendars")
    tasks_cal = core.get_config(conn, "caldav_tasks_calendar")
    if not username or not password:
        return None
    return CalDAVClient(
        url=url, username=username, password=password,
        read_calendars=read_cals, tasks_calendar=tasks_cal,
    )
```

- [ ] **Step 4: Fix `cli.py` `_get_caldav_client()`**

Replace lines 40–50 in `src/timeopt/cli.py`:

```python
def _get_caldav_client(conn):
    from timeopt.caldav_client import CalDAVClient
    url = core.get_config(conn, "caldav_url")
    username = core.get_config(conn, "caldav_username")
    password = core.get_config(conn, "caldav_password")
    read_cals = core.get_config(conn, "caldav_read_calendars")
    tasks_cal = core.get_config(conn, "caldav_tasks_calendar")
    if not username or not password:
        return None
    return CalDAVClient(url=url, username=username, password=password,
                        read_calendars=read_cals, tasks_calendar=tasks_cal)
```

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add src/timeopt/server.py src/timeopt/cli.py tests/test_server.py
git commit -m "fix: remove inline caldav fallbacks; read from config defaults"
```

---

## Task 3: Add `max_tokens` to `AnthropicClient`

**Files:**
- Modify: `src/timeopt/llm_client.py:24-44`
- Modify: `tests/test_llm.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_llm.py — add at the bottom

def test_anthropic_client_passes_max_tokens():
    """AnthropicClient.complete() uses max_tokens from __init__."""
    with patch("timeopt.llm_client.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="ok")]
        )
        client = AnthropicClient(api_key="test-key", model="claude-sonnet-4-6", max_tokens=1024)
        client.complete(system="sys", user="user")
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["max_tokens"] == 1024


def test_build_llm_client_passes_max_tokens_to_anthropic():
    """build_llm_client reads llm_max_tokens from config and passes to AnthropicClient."""
    with patch("timeopt.llm_client.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="ok")]
        )
        config = {"llm_api_key": "test-key", "llm_model": "claude-sonnet-4-6", "llm_max_tokens": "2048"}
        client = build_llm_client(config)
        client.complete(system="s", user="u")
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["max_tokens"] == 2048
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_llm.py::test_anthropic_client_passes_max_tokens tests/test_llm.py::test_build_llm_client_passes_max_tokens_to_anthropic -v
```
Expected: `FAILED` — `TypeError: __init__() got an unexpected keyword argument 'max_tokens'`

- [ ] **Step 3: Update `AnthropicClient` and `build_llm_client`**

Replace `AnthropicClient` and `build_llm_client` in `src/timeopt/llm_client.py`:

```python
class AnthropicClient(LLMClient):
    def __init__(self, api_key: str | None, model: str, max_tokens: int = 4096):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Set it via environment variable or timeopt config: "
                "timeopt config set llm_api_key <key>"
            )
        self._client = anthropic.Anthropic(api_key=key)
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        result = response.content[0].text
        logger.debug("AnthropicClient.complete: %d chars", len(result))
        return result


def build_llm_client(config: dict) -> LLMClient:
    """
    Build the appropriate LLM client from config.
    Uses OpenAICompatibleClient if llm_base_url is set, else AnthropicClient.
    """
    max_tokens = int(config.get("llm_max_tokens") or "4096")
    if config.get("llm_base_url"):
        return OpenAICompatibleClient(
            base_url=config["llm_base_url"],
            api_key=config.get("llm_api_key", ""),
            model=config.get("llm_model", "claude-sonnet-4-6"),
        )
    return AnthropicClient(
        api_key=config.get("llm_api_key"),
        model=config.get("llm_model", "claude-sonnet-4-6"),
        max_tokens=max_tokens,
    )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_llm.py -v
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/llm_client.py tests/test_llm.py
git commit -m "feat(llm): make max_tokens configurable via llm_max_tokens config key"
```

---

## Task 4: Make `resolve_calendar_reference` use configurable `min_score`

**Files:**
- Modify: `src/timeopt/core.py:378-396` (function signature + body)
- Modify: `src/timeopt/core.py:524-554` (`try_resolve_unresolved` — read min_score from config)
- Modify: `src/timeopt/server.py` (pass min_score when calling `core.resolve_calendar_reference`)
- Modify: `tests/test_core_integrations.py` (add min_score test)

- [ ] **Step 1: Write failing test**

```python
# tests/test_core_integrations.py — add at the bottom
# (Uses CalendarEvent objects — check existing imports in this file first)

def test_resolve_calendar_reference_respects_min_score(conn):
    from timeopt.core import resolve_calendar_reference
    from timeopt.caldav_client import CalendarEvent
    events = [
        CalendarEvent(title="Team sync", start="2026-04-02T09:00:00Z",
                      end="2026-04-02T10:00:00Z", uid="uid-1"),
    ]
    # Low min_score — "sync" should match "Team sync"
    result_low = resolve_calendar_reference("sync", events, min_score=10)
    assert result_low is not None

    # High min_score — "sync" alone won't score high enough against "Team sync"
    result_high = resolve_calendar_reference("sync", events, min_score=95)
    assert result_high is None
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
uv run pytest tests/test_core_integrations.py::test_resolve_calendar_reference_respects_min_score -v
```
Expected: `FAILED` — `TypeError: resolve_calendar_reference() got an unexpected keyword argument 'min_score'`

- [ ] **Step 3: Add `min_score` param to `resolve_calendar_reference` in `core.py`**

Update the function signature and comparison (around line 378):

```python
def resolve_calendar_reference(
    label: str,
    events: list,
    min_score: int = 50,
) -> dict | None:
    """
    Fuzzy-match a textual event label against a list of CalendarEvent objects.
    Returns the best match as {uid, title, start, end, score} or None.
    """
    if not events:
        return None
    titles = [ev.title for ev in events]
    results = fuzz_process.extractOne(label, titles)
    if results is None:
        return None
    title, score, idx = results
    if score < min_score:
        return None
    ev = events[idx]
    return {"uid": ev.uid, "title": ev.title, "start": ev.start, "end": ev.end, "score": score}
```

- [ ] **Step 4: Update `try_resolve_unresolved` to read `calendar_fuzzy_min_score` from config**

In `src/timeopt/core.py`, update `try_resolve_unresolved` (around line 524) to read config and pass min_score:

```python
def try_resolve_unresolved(conn: sqlite3.Connection, events: list) -> list[dict]:
    """
    Attempt to bind unresolved tasks to calendar events.
    Returns list of {display_id, status: "resolved" | "still_unresolved"}.
    """
    unresolved = get_unresolved_tasks(conn)
    results = []
    min_score = int(get_config(conn, "calendar_fuzzy_min_score"))
    for task in unresolved:
        label = task["due_event_label"]
        if not label:
            continue
        match = resolve_calendar_reference(label, events, min_score=min_score)
        if match:
            event_start = datetime.fromisoformat(
                match["start"].replace("Z", "+00:00")
            )
            row = conn.execute(
                "SELECT due_event_offset_min FROM tasks WHERE id=?", (task["id"],)
            ).fetchone()
            offset = row[0] if row and row[0] is not None else 0
            new_due_at = (event_start + timedelta(minutes=offset)).isoformat()
            conn.execute(
                "UPDATE tasks SET due_event_uid=?, due_at=?, due_unresolved=0 WHERE id=?",
                (match["uid"], new_due_at, task["id"]),
            )
            conn.commit()
            results.append({"display_id": task["display_id"], "status": "resolved"})
            logger.info("resolved task %s to event uid=%s", task["display_id"], match["uid"])
        else:
            results.append({"display_id": task["display_id"], "status": "still_unresolved"})
    return results
```

- [ ] **Step 5: Update `server.py` `resolve_calendar_reference` tool to pass min_score**

In `src/timeopt/server.py`, find the `resolve_calendar_reference` MCP tool (around line 253) and update the call to `core.resolve_calendar_reference`:

```python
@mcp.tool()
def resolve_calendar_reference(label: str, date_range: Optional[dict] = None) -> dict:
    """
    Fuzzy-match a textual event label against real CalDAV events.
    Returns {candidates: [{uid, title, start, end, score}]}.
    date_range: optional {start: "YYYY-MM-DD", end: "YYYY-MM-DD"} (default: next 30 days).
    """
    conn = _open_conn()
    try:
        caldav = _get_caldav(conn)
        if not caldav:
            return {"candidates": [], "error": "CalDAV not configured"}
        start_date = _date_type.today()
        days = 30
        if date_range:
            if date_range.get("start"):
                start_date = _datetime.fromisoformat(date_range["start"]).date()
            if date_range.get("end"):
                end_date = _datetime.fromisoformat(date_range["end"]).date()
                days = max(1, (end_date - start_date).days)
        events_raw = caldav.get_events(start_date.isoformat(), days=days)
        min_score = int(core.get_config(conn, "calendar_fuzzy_min_score"))
        match = core.resolve_calendar_reference(label, events_raw, min_score=min_score)
        return {"candidates": [match] if match else []}
    finally:
        conn.close()
```

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
git add src/timeopt/core.py src/timeopt/server.py tests/test_core_integrations.py
git commit -m "feat(config): make calendar fuzzy min_score configurable"
```

---

## Task 5: Add `timeopt setup` CLI command

**Files:**
- Modify: `src/timeopt/cli.py` (add `setup` command after existing `config` group)
- Modify: `tests/test_cli.py` (add setup tests)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli.py — add at the bottom

def test_setup_skips_all(runner, cli_env):
    """Choosing skip for all sections runs without error."""
    from timeopt.cli import cli
    result = runner.invoke(cli, ["setup"], input="4\nn\nn\nn\n")
    assert result.exit_code == 0
    assert "Setup complete" in result.output


def test_setup_anthropic_saves_config(runner, cli_env):
    """Choosing Anthropic saves llm_api_key and llm_model."""
    from timeopt.cli import cli
    from timeopt import db, core
    result = runner.invoke(
        cli, ["setup"],
        input="1\nsk-test-key\nclaude-sonnet-4-6\nn\nn\nn\n"
    )
    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert core.get_config(conn, "llm_api_key") == "sk-test-key"
    assert core.get_config(conn, "llm_model") == "claude-sonnet-4-6"
    conn.close()


def test_setup_openai_sets_base_url(runner, cli_env):
    """Choosing OpenAI sets llm_base_url to OpenAI's API."""
    from timeopt.cli import cli
    from timeopt import db, core
    result = runner.invoke(
        cli, ["setup"],
        input="2\nsk-openai-key\ngpt-4o\nn\nn\nn\n"
    )
    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert core.get_config(conn, "llm_base_url") == "https://api.openai.com/v1"
    assert core.get_config(conn, "llm_api_key") == "sk-openai-key"
    conn.close()


def test_setup_scheduling_defaults(runner, cli_env):
    """Customizing scheduling saves day_start and day_end."""
    from timeopt.cli import cli
    from timeopt import db, core
    result = runner.invoke(
        cli, ["setup"],
        input="4\nn\ny\n08:00\n17:00\n10\nsmall\nn\n"
    )
    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert core.get_config(conn, "day_start") == "08:00"
    assert core.get_config(conn, "day_end") == "17:00"
    conn.close()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_cli.py::test_setup_skips_all tests/test_cli.py::test_setup_anthropic_saves_config -v
```
Expected: `FAILED` — `No such command 'setup'`

- [ ] **Step 3: Add `setup` command to `cli.py`**

Add after the `config` group (after the `config_set` command definition), before the `done` command:

```python
@cli.command()
def setup():
    """Interactive setup wizard. Configures LLM, CalDAV, and scheduling defaults."""
    conn = _open_conn()
    try:
        cfg = core.get_all_config(conn)

        llm_ok = bool(cfg.get("llm_api_key"))
        caldav_ok = bool(cfg.get("caldav_username") and cfg.get("caldav_password"))
        click.echo("Current state:")
        click.echo(f"  LLM:    {'configured' if llm_ok else 'not set'}")
        click.echo(f"  CalDAV: {'configured' if caldav_ok else 'not set'}")
        click.echo("")

        # Step 1: LLM provider
        click.echo("LLM provider:")
        click.echo("  1. Anthropic")
        click.echo("  2. OpenAI")
        click.echo("  3. Custom (OpenAI-compatible)")
        click.echo("  4. Skip")
        choice = click.prompt("Choice", type=click.Choice(["1", "2", "3", "4"]), default="4")

        if choice == "1":
            api_key = click.prompt("Anthropic API key",
                                   default=cfg.get("llm_api_key") or "", hide_input=True)
            model = click.prompt("Model", default=cfg.get("llm_model") or "claude-sonnet-4-6")
            core.set_config(conn, "llm_api_key", api_key)
            core.set_config(conn, "llm_model", model)
        elif choice == "2":
            api_key = click.prompt("OpenAI API key",
                                   default=cfg.get("llm_api_key") or "", hide_input=True)
            model = click.prompt("Model", default=cfg.get("llm_model") or "gpt-4o")
            core.set_config(conn, "llm_base_url", "https://api.openai.com/v1")
            core.set_config(conn, "llm_api_key", api_key)
            core.set_config(conn, "llm_model", model)
        elif choice == "3":
            base_url = click.prompt("Base URL", default=cfg.get("llm_base_url") or "")
            api_key = click.prompt("API key",
                                   default=cfg.get("llm_api_key") or "", hide_input=True)
            model = click.prompt("Model", default=cfg.get("llm_model") or "")
            core.set_config(conn, "llm_base_url", base_url)
            core.set_config(conn, "llm_api_key", api_key)
            core.set_config(conn, "llm_model", model)

        # Step 2: CalDAV
        if click.confirm("\nConfigure CalDAV (Yandex Calendar or any CalDAV server)?", default=False):
            url = click.prompt("CalDAV URL",
                               default=cfg.get("caldav_url") or "https://caldav.yandex.ru")
            username = click.prompt("Username", default=cfg.get("caldav_username") or "")
            password = click.prompt("Password",
                                    default=cfg.get("caldav_password") or "", hide_input=True)
            core.set_config(conn, "caldav_url", url)
            core.set_config(conn, "caldav_username", username)
            core.set_config(conn, "caldav_password", password)

        # Step 3: Scheduling defaults
        if click.confirm("\nCustomize scheduling defaults?", default=False):
            day_start = click.prompt("Day start (HH:MM)",
                                     default=cfg.get("day_start") or "09:00")
            day_end = click.prompt("Day end (HH:MM)",
                                   default=cfg.get("day_end") or "18:00")
            break_min = click.prompt("Break between tasks (minutes)",
                                     default=cfg.get("break_duration_min") or "15")
            default_effort = click.prompt(
                "Default effort",
                default=cfg.get("default_effort") or "medium",
                type=click.Choice(["small", "medium", "large"]),
            )
            core.set_config(conn, "day_start", day_start)
            core.set_config(conn, "day_end", day_end)
            core.set_config(conn, "break_duration_min", break_min)
            core.set_config(conn, "default_effort", default_effort)

        # Step 4: Web UI
        if click.confirm("\nOpen web UI?", default=False):
            click.echo("Run: timeopt ui")

        click.echo("\nSetup complete.")
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_cli.py -v
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/cli.py tests/test_cli.py
git commit -m "feat(cli): add interactive setup wizard command"
```

---

## Task 6: Add `/timeopt:setup` slash command

**Files:**
- Create: `commands/setup.md`

- [ ] **Step 1: Create `commands/setup.md`**

```markdown
# /timeopt:setup

Interactive setup wizard for timeopt. Walks through configuring LLM, CalDAV, and scheduling defaults.

## Steps

1. Call `get_config` (no key argument) to see what's currently configured.

2. Tell the user what's already configured and what's missing:
   - LLM: check if `llm_api_key` is set
   - CalDAV: check if `caldav_username` and `caldav_password` are set
   - Show current values for any configured items (mask passwords)

3. **LLM provider** — ask the user which provider they want to use:
   - **Anthropic**: ask for `llm_api_key` and `llm_model` (suggest `claude-sonnet-4-6`). Call `set_config` for each.
   - **OpenAI**: set `llm_base_url` to `https://api.openai.com/v1`, ask for `llm_api_key` and `llm_model` (suggest `gpt-4o`). Call `set_config` for each.
   - **Custom (OpenAI-compatible)**: ask for `llm_base_url`, `llm_api_key`, and `llm_model`. Call `set_config` for each.
   - **Skip**: move on.

4. **CalDAV** — ask "Would you like to configure CalDAV integration? (Yandex Calendar or any CalDAV server)"
   - If yes: ask for `caldav_url` (default: `https://caldav.yandex.ru`), `caldav_username`, `caldav_password`. Call `set_config` for each.
   - If no: skip.

5. **Scheduling defaults** — ask "Would you like to customize scheduling defaults?"
   - If yes: ask for `day_start` (default: `09:00`), `day_end` (default: `18:00`), `break_duration_min` (default: `15`), `default_effort` (default: `medium`). Call `set_config` for each.
   - If no: skip.

6. **Web UI** — ask "Would you like to open the timeopt web UI?"
   - If yes: tell the user to run `timeopt ui` in their terminal, or use the terminal tool to run it.
   - If no: skip.

7. Summarize what was configured.

## Notes

- Always mask passwords when showing current values (show `***` instead)
- If a value is already set, show the current value as the suggested default
- `set_config` accepts string values only — all config values are stored as strings
- Valid effort values: `small`, `medium`, `large`
```

- [ ] **Step 2: Verify the file exists and looks right**

```bash
cat commands/setup.md
```

- [ ] **Step 3: Commit**

```bash
git add commands/setup.md
git commit -m "feat(commands): add /timeopt:setup slash command"
```

---

## Task 7: Add web UI dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependencies**

Add to the `dependencies` list in `pyproject.toml`:

```toml
[project]
dependencies = [
    "fastmcp>=2.0",
    "caldav>=1.3",
    "click>=8.1",
    "anthropic>=0.40",
    "openai>=1.0",
    "rapidfuzz>=3.0",
    "icalendar>=7.0.3",
    "fastapi>=0.100",
    "uvicorn>=0.24",
    "jinja2>=3.1",
    "python-multipart>=0.0.7",
]
```

- [ ] **Step 2: Install**

```bash
uv sync
```
Expected: resolves and installs new packages without error

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add fastapi, uvicorn, jinja2, python-multipart for web UI"
```

---

## Task 8: Create `ui_server.py`

**Files:**
- Create: `src/timeopt/ui_server.py`
- Create: `tests/test_ui_server.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ui_server.py

import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from timeopt import db, core


@pytest.fixture
def ui_env(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = db.get_connection(db_path)
    db.create_schema(conn)
    conn.close()
    with patch.dict(os.environ, {"TIMEOPT_DB": db_path}):
        yield db_path


def test_root_redirects_to_config(ui_env):
    from timeopt.ui_server import app
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/")
    assert resp.status_code in (301, 302, 307, 308)
    assert "/config" in resp.headers["location"]


def test_config_page_returns_html(ui_env):
    from timeopt.ui_server import app
    client = TestClient(app)
    resp = client.get("/config")
    assert resp.status_code == 200
    assert "timeopt" in resp.text
    assert "day_start" in resp.text


def test_config_partial_returns_html(ui_env):
    from timeopt.ui_server import app
    client = TestClient(app)
    resp = client.get("/partials/config")
    assert resp.status_code == 200
    assert "day_start" in resp.text


def test_post_config_saves_value(ui_env):
    from timeopt.ui_server import app
    client = TestClient(app)
    resp = client.post("/api/config/day_start", data={"value": "08:00"})
    assert resp.status_code == 200
    assert "saved" in resp.text.lower()
    # Verify it was actually persisted
    conn = db.get_connection(ui_env)
    assert core.get_config(conn, "day_start") == "08:00"
    conn.close()


def test_post_config_unknown_key_returns_error(ui_env):
    from timeopt.ui_server import app
    client = TestClient(app)
    resp = client.post("/api/config/totally_unknown_key", data={"value": "foo"})
    assert resp.status_code == 200
    assert "error" in resp.text.lower()


def test_get_config_api_returns_all(ui_env):
    from timeopt.ui_server import app
    client = TestClient(app)
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "day_start" in data
    assert data["day_start"] == "09:00"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_ui_server.py -v
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'timeopt.ui_server'`

- [ ] **Step 3: Create `src/timeopt/ui_server.py`**

```python
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from timeopt import core, db

logger = logging.getLogger(__name__)

app = FastAPI(title="timeopt")
_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_DEFAULT_DB = str(Path.home() / ".timeopt" / "tasks.db")


def _db_path() -> str:
    return os.environ.get("TIMEOPT_DB", _DEFAULT_DB)


def _open_conn():
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = db.get_connection(path)
    db.create_schema(conn)
    return conn


@app.get("/", response_class=RedirectResponse)
async def root():
    return RedirectResponse(url="/config")


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    conn = _open_conn()
    try:
        cfg = core.get_all_config(conn)
        return templates.TemplateResponse(
            "config.html", {"request": request, "config": cfg}
        )
    finally:
        conn.close()


@app.get("/partials/config", response_class=HTMLResponse)
async def config_partial(request: Request):
    conn = _open_conn()
    try:
        cfg = core.get_all_config(conn)
        return templates.TemplateResponse(
            "partials/config.html", {"request": request, "config": cfg}
        )
    finally:
        conn.close()


@app.post("/api/config/{key}", response_class=HTMLResponse)
async def set_config_field(request: Request, key: str, value: str = Form("")):
    conn = _open_conn()
    try:
        try:
            core.set_config(conn, key, value)
            return templates.TemplateResponse(
                "partials/config_field.html",
                {"request": request, "key": key, "value": value, "status": "saved"},
            )
        except KeyError as e:
            return templates.TemplateResponse(
                "partials/config_field.html",
                {
                    "request": request, "key": key, "value": value,
                    "status": "error", "error": str(e),
                },
            )
    finally:
        conn.close()


@app.get("/api/config")
async def get_all_config_api():
    conn = _open_conn()
    try:
        return JSONResponse(content=core.get_all_config(conn))
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests (they will fail until templates exist — that's Task 9)**

```bash
uv run pytest tests/test_ui_server.py -v
```
Expected: `FAILED` — `jinja2.exceptions.TemplateNotFound: config.html`

- [ ] **Step 5: Commit the server file**

```bash
git add src/timeopt/ui_server.py tests/test_ui_server.py
git commit -m "feat(ui): add FastAPI ui_server with config routes"
```

---

## Task 9: Create templates

**Files:**
- Create: `src/timeopt/templates/base.html`
- Create: `src/timeopt/templates/config.html`
- Create: `src/timeopt/templates/partials/config.html`
- Create: `src/timeopt/templates/partials/config_field.html`

- [ ] **Step 1: Create `src/timeopt/templates/base.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>timeopt</title>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { display: flex; font-family: system-ui, -apple-system, sans-serif; height: 100vh; background: #f8f9fa; }
    .sidebar {
      width: 200px; background: #1a1a2e; color: #eee;
      padding: 1.5rem 1rem; flex-shrink: 0; display: flex; flex-direction: column;
    }
    .sidebar h1 { font-size: 1.1rem; font-weight: 700; margin-bottom: 2rem; color: #7c83fd; letter-spacing: 0.02em; }
    .sidebar nav a {
      display: block; padding: 0.5rem 0.75rem; color: #aaa;
      text-decoration: none; border-radius: 4px; margin-bottom: 0.25rem;
      cursor: pointer; font-size: 0.875rem; transition: background 0.15s, color 0.15s;
    }
    .sidebar nav a:hover { background: #2a2a4e; color: #fff; }
    .sidebar nav a.active { background: #2a2a4e; color: #fff; }
    #content { flex: 1; overflow-y: auto; padding: 2rem 2.5rem; }
  </style>
</head>
<body>
  <div class="sidebar">
    <h1>timeopt</h1>
    <nav>
      <a hx-get="/partials/config"
         hx-target="#content"
         hx-push-url="/config"
         class="{% block nav_config_active %}{% endblock %}">Config</a>
    </nav>
  </div>
  <div id="content">
    {% block content %}{% endblock %}
  </div>
</body>
</html>
```

- [ ] **Step 2: Create `src/timeopt/templates/config.html`**

```html
{% extends "base.html" %}
{% block nav_config_active %}active{% endblock %}
{% block content %}
{% include "partials/config.html" %}
{% endblock %}
```

- [ ] **Step 3: Create `src/timeopt/templates/partials/config_field.html`**

```html
<div id="field-{{ key }}" class="field-row">
  <label class="field-label">{{ key }}</label>
  <input
    class="field-input"
    name="value"
    value="{{ value if value is not none else '' }}"
    type="{{ 'password' if 'password' in key or key == 'llm_api_key' else 'text' }}"
    hx-post="/api/config/{{ key }}"
    hx-target="#field-{{ key }}"
    hx-trigger="change"
    hx-include="this"
  />
  <span class="field-status {{ status }}">
    {%- if status == 'saved' %}✓ saved
    {%- elif status == 'error' %}✗ {{ error }}
    {%- endif -%}
  </span>
</div>
```

- [ ] **Step 4: Create `src/timeopt/templates/partials/config.html`**

```html
<style>
  h2.page-title { font-size: 1.3rem; font-weight: 600; margin-bottom: 1.75rem; color: #111; }
  .config-section { margin-bottom: 2rem; background: #fff; border-radius: 8px; border: 1px solid #e5e7eb; overflow: hidden; }
  .config-section-header {
    font-size: 0.7rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.08em; color: #6b7280; padding: 0.75rem 1rem;
    background: #f9fafb; border-bottom: 1px solid #e5e7eb;
  }
  .field-row { display: flex; align-items: center; gap: 1rem; padding: 0.625rem 1rem; border-bottom: 1px solid #f3f4f6; }
  .field-row:last-child { border-bottom: none; }
  .field-label { width: 220px; font-size: 0.8rem; color: #374151; font-family: monospace; flex-shrink: 0; }
  .field-input {
    flex: 1; max-width: 380px; padding: 0.375rem 0.625rem;
    border: 1px solid #d1d5db; border-radius: 4px; font-size: 0.8rem;
    outline: none; transition: border-color 0.15s;
  }
  .field-input:focus { border-color: #7c83fd; }
  .field-status { font-size: 0.7rem; min-width: 70px; color: #9ca3af; }
  .field-status.saved { color: #22c55e; }
  .field-status.error { color: #ef4444; }
</style>

<h2 class="page-title">Configuration</h2>

{% macro render_field(key) %}
{% set value = config.get(key) %}
{% include "partials/config_field.html" %}
{% endmacro %}

<div class="config-section">
  <div class="config-section-header">LLM</div>
  {{ render_field("llm_api_key") }}
  {{ render_field("llm_model") }}
  {{ render_field("llm_max_tokens") }}
  {{ render_field("llm_base_url") }}
</div>

<div class="config-section">
  <div class="config-section-header">CalDAV</div>
  {{ render_field("caldav_url") }}
  {{ render_field("caldav_username") }}
  {{ render_field("caldav_password") }}
  {{ render_field("caldav_read_calendars") }}
  {{ render_field("caldav_tasks_calendar") }}
</div>

<div class="config-section">
  <div class="config-section-header">Scheduling</div>
  {{ render_field("day_start") }}
  {{ render_field("day_end") }}
  {{ render_field("break_duration_min") }}
  {{ render_field("default_effort") }}
  {{ render_field("effort_small_min") }}
  {{ render_field("effort_medium_min") }}
  {{ render_field("effort_large_min") }}
</div>

<div class="config-section">
  <div class="config-section-header">Behavior</div>
  {{ render_field("hide_done_after_days") }}
  {{ render_field("fuzzy_match_min_score") }}
  {{ render_field("fuzzy_match_ask_gap") }}
  {{ render_field("delegation_max_tool_calls") }}
  {{ render_field("calendar_fuzzy_min_score") }}
  {{ render_field("ui_port") }}
</div>
```

- [ ] **Step 5: Run all UI server tests**

```bash
uv run pytest tests/test_ui_server.py -v
```
Expected: all PASSED

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
git add src/timeopt/templates/ tests/test_ui_server.py
git commit -m "feat(ui): add HTMX/Jinja2 templates for config page"
```

---

## Task 10: Add `timeopt ui` CLI command

**Files:**
- Modify: `src/timeopt/cli.py` (add `ui` command)
- Modify: `tests/test_cli.py` (add ui tests)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli.py — add at the bottom

def test_ui_command_starts_uvicorn(runner, cli_env):
    """timeopt ui starts uvicorn and opens browser."""
    from timeopt.cli import cli
    with patch("uvicorn.run") as mock_uvicorn, \
         patch("webbrowser.open") as mock_browser:
        result = runner.invoke(cli, ["ui"])
        assert result.exit_code == 0
        mock_uvicorn.assert_called_once()
        call_args = mock_uvicorn.call_args
        assert "timeopt.ui_server:app" in call_args[0]
        mock_browser.assert_called_once()
        assert "7749" in mock_browser.call_args[0][0]


def test_ui_command_respects_ui_port_config(runner, cli_env):
    """timeopt ui reads ui_port from config."""
    from timeopt.cli import cli
    from timeopt import db, core
    conn = db.get_connection(cli_env)
    core.set_config(conn, "ui_port", "9000")
    conn.close()

    with patch("uvicorn.run") as mock_uvicorn, \
         patch("webbrowser.open") as mock_browser:
        result = runner.invoke(cli, ["ui"])
        assert result.exit_code == 0
        call_kwargs = mock_uvicorn.call_args[1]
        assert call_kwargs["port"] == 9000
        assert "9000" in mock_browser.call_args[0][0]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_cli.py::test_ui_command_starts_uvicorn -v
```
Expected: `FAILED` — `No such command 'ui'`

- [ ] **Step 3: Add `ui` command to `cli.py`**

Add at the end of `cli.py`, before or after the `sync` command:

```python
@cli.command()
def ui():
    """Start the timeopt web UI and open it in a browser."""
    import webbrowser
    import uvicorn

    conn = _open_conn()
    try:
        port = int(core.get_config(conn, "ui_port") or "7749")
    finally:
        conn.close()

    url = f"http://127.0.0.1:{port}"
    click.echo(f"Starting timeopt UI at {url}  (Ctrl+C to stop)")
    webbrowser.open(url)
    uvicorn.run("timeopt.ui_server:app", host="127.0.0.1", port=port)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_cli.py -v
```
Expected: all PASSED

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add src/timeopt/cli.py tests/test_cli.py
git commit -m "feat(cli): add 'timeopt ui' command to launch web UI"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Part 1 (config defaults) → Tasks 1–4. Part 2 (setup) → Tasks 5–6. Part 3 (web UI) → Tasks 7–10.
- [x] **No placeholders:** All code blocks are complete.
- [x] **Type consistency:** `resolve_calendar_reference` signature in Task 4 matches all call sites updated in the same task. `AnthropicClient(max_tokens=...)` in Task 3 matches `build_llm_client` update in same task.
- [x] **`_CONFIG_OPTIONAL` shrink:** After Task 1, `caldav_url`, `caldav_read_calendars`, `caldav_tasks_calendar` are no longer in `_CONFIG_OPTIONAL` — they have defaults. `get_config` for these keys will never return `None`.
- [x] **Jinja2 macro scoping:** The `render_field` macro in `partials/config.html` uses `{% set value = config.get(key) %}` then `{% include %}`. Jinja2 includes do share the caller's context, so `key` and `value` are available in `config_field.html`.
- [x] **HTMX `hx-include`:** `hx-include="this"` on the `<input>` sends the `value` form field on `change`. FastAPI reads it via `value: str = Form("")`. This is correct.
- [x] **Browser opens before uvicorn blocks:** `webbrowser.open` is called before `uvicorn.run` so the browser fires even though uvicorn blocks the terminal thread.
