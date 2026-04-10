# Timeopt Integrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the LLM client abstraction, CalDAV integration, brain dump template generation, transactional calendar block pushing, and `/sync` logic to the timeopt core.

**Architecture:** Two new modules — `llm_client.py` (LLM abstraction) and `caldav_client.py` (CalDAV read/write). `core.py` gains `get_dump_templates`, `dump_task`, `dump_tasks`. `planner.py` gains transactional `push_calendar_blocks`. All external services are stubbed in tests.

**Prerequisites:** Plan 1 (Core Backend) must be fully implemented and passing.

**Tech Stack:** `caldav`, `anthropic`, `openai`, `rapidfuzz`, `pytest`

---

## File Map

| File | Responsibility |
|---|---|
| `src/timeopt/llm_client.py` | LLM abstraction: `AnthropicClient`, `OpenAICompatibleClient` |
| `src/timeopt/caldav_client.py` | CalDAV read (events), write (create/delete), sync token |
| `src/timeopt/core.py` (modify) | `get_dump_templates`, `dump_task`, `dump_tasks`, `resolve_calendar_reference` |
| `src/timeopt/planner.py` (modify) | `push_calendar_blocks` transactional, `/sync` algorithmic logic |
| `tests/test_llm.py` | LLMClient interface contract |
| `tests/test_caldav.py` | CalDAV client with mocked server responses |
| `tests/test_core_integrations.py` | dump templates, task saving, calendar binding |
| `tests/test_sync.py` | Algorithmic sync, unresolved re-binding |

---

## Task 1: LLM Client Abstraction

**Files:**
- Create: `src/timeopt/llm_client.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: Write failing tests**

`tests/test_llm.py`:
```python
from unittest.mock import MagicMock, patch
from timeopt.llm_client import AnthropicClient, OpenAICompatibleClient, LLMClient


def test_anthropic_client_implements_interface():
    assert hasattr(AnthropicClient, "complete")


def test_openai_compatible_client_implements_interface():
    assert hasattr(OpenAICompatibleClient, "complete")


def test_anthropic_client_calls_api():
    with patch("timeopt.llm_client.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="response text")]
        )
        client = AnthropicClient(api_key="test-key", model="claude-sonnet-4-6")
        result = client.complete(system="sys", user="user msg")
        assert result == "response text"
        mock_client.messages.create.assert_called_once()


def test_openai_compatible_client_calls_api():
    with patch("timeopt.llm_client.openai") as mock_openai:
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="response text"))]
        )
        client = OpenAICompatibleClient(
            base_url="http://localhost:11434/v1",
            api_key="test",
            model="llama3",
        )
        result = client.complete(system="sys", user="user msg")
        assert result == "response text"


def test_anthropic_client_missing_key_raises():
    import pytest
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            AnthropicClient(api_key=None, model="claude-sonnet-4-6")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_llm.py -v
```

Expected: `ModuleNotFoundError: No module named 'timeopt.llm_client'`

- [ ] **Step 3: Write `src/timeopt/llm_client.py`**

```python
import logging
import os

logger = logging.getLogger(__name__)

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore

try:
    import openai
except ImportError:
    openai = None  # type: ignore


class LLMClient:
    """Abstract LLM client interface."""

    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str | None, model: str):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Set it via environment variable or timeopt config: "
                "timeopt config set llm_api_key <key>"
            )
        self._client = anthropic.Anthropic(api_key=key)
        self._model = model

    def complete(self, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        result = response.content[0].text
        logger.debug("AnthropicClient.complete: %d chars", len(result))
        return result


class OpenAICompatibleClient(LLMClient):
    def __init__(self, base_url: str, api_key: str, model: str):
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    def complete(self, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        result = response.choices[0].message.content
        logger.debug("OpenAICompatibleClient.complete: %d chars", len(result))
        return result


def build_llm_client(config: dict) -> LLMClient:
    """
    Build the appropriate LLM client from config.
    Uses OpenAICompatibleClient if llm_base_url is set, else AnthropicClient.
    """
    if config.get("llm_base_url"):
        return OpenAICompatibleClient(
            base_url=config["llm_base_url"],
            api_key=config.get("llm_api_key", ""),
            model=config.get("llm_model", "claude-sonnet-4-6"),
        )
    return AnthropicClient(
        api_key=config.get("llm_api_key"),
        model=config.get("llm_model", "claude-sonnet-4-6"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_llm.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/llm_client.py tests/test_llm.py
git commit -m "feat: LLM client abstraction (Anthropic + OpenAI-compatible)"
```

---

## Task 2: CalDAV Client — Read

**Files:**
- Create: `src/timeopt/caldav_client.py`
- Create: `tests/test_caldav.py`

- [ ] **Step 1: Write failing tests**

`tests/test_caldav.py`:
```python
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone
from timeopt.caldav_client import CalDAVClient, CalendarEvent


def _mock_event(title: str, start: str, end: str):
    ev = MagicMock()
    ev.instance.vevent.summary.value = title
    ev.instance.vevent.dtstart.value = datetime.fromisoformat(start)
    ev.instance.vevent.dtend.value = datetime.fromisoformat(end)
    ev.instance.vevent.uid.value = f"uid-{title}"
    return ev


def test_get_events_returns_list(conn):
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal
        mock_cal = MagicMock()
        mock_principal.calendars.return_value = [mock_cal]
        type(mock_cal).name = PropertyMock(return_value="Work")

        ev1 = _mock_event("Standup", "2026-03-28T09:00:00+00:00", "2026-03-28T10:00:00+00:00")
        mock_cal.date_search.return_value = [ev1]

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )
        events = client.get_events("2026-03-28")

    assert len(events) == 1
    assert events[0].title == "Standup"
    assert events[0].start == "2026-03-28T09:00:00+00:00"


def test_get_events_filters_by_calendar_name(conn):
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal

        work_cal = MagicMock()
        type(work_cal).name = PropertyMock(return_value="Work")
        personal_cal = MagicMock()
        type(personal_cal).name = PropertyMock(return_value="Personal")
        mock_principal.calendars.return_value = [work_cal, personal_cal]

        work_cal.date_search.return_value = [
            _mock_event("Standup", "2026-03-28T09:00:00+00:00", "2026-03-28T10:00:00+00:00")
        ]
        personal_cal.date_search.return_value = []

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="Work",  # only Work calendar
            tasks_calendar="Timeopt",
        )
        events = client.get_events("2026-03-28")

    assert len(events) == 1
    work_cal.date_search.assert_called_once()
    personal_cal.date_search.assert_not_called()


def test_caldav_unreachable_returns_empty():
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_caldav.DAVClient.side_effect = Exception("Connection refused")
        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )
        events = client.get_events("2026-03-28")
    assert events == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_caldav.py -v
```

Expected: `ModuleNotFoundError: No module named 'timeopt.caldav_client'`

- [ ] **Step 3: Write `src/timeopt/caldav_client.py`**

```python
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

try:
    import caldav
except ImportError:
    caldav = None  # type: ignore


@dataclass
class CalendarEvent:
    uid: str
    title: str
    start: str  # ISO8601 UTC
    end: str    # ISO8601 UTC


def _to_utc_iso(dt) -> str:
    """Convert a datetime (possibly naive) to UTC ISO8601 string."""
    if hasattr(dt, "astimezone"):
        return dt.astimezone(timezone.utc).isoformat()
    return str(dt)


class CalDAVClient:
    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        read_calendars: str = "all",
        tasks_calendar: str = "Timeopt",
    ):
        self._url = url
        self._username = username
        self._password = password
        self._read_calendars = read_calendars  # "all" or comma-separated names
        self._tasks_calendar = tasks_calendar

    def _read_calendar_names(self) -> set[str] | None:
        """Return set of calendar names to read, or None for all."""
        if self._read_calendars == "all":
            return None
        return {n.strip() for n in self._read_calendars.split(",")}

    def get_events(self, date: str, days: int = 1) -> list[CalendarEvent]:
        """
        Fetch events for the given date range.
        Returns [] on connection failure (warn, don't raise).
        """
        try:
            start = datetime.fromisoformat(f"{date}T00:00:00+00:00")
            end = start + timedelta(days=days)
            allowed = self._read_calendar_names()

            events: list[CalendarEvent] = []
            with caldav.DAVClient(
                url=self._url,
                username=self._username,
                password=self._password,
            ) as client:
                principal = client.principal()
                for cal in principal.calendars():
                    if allowed is not None and cal.name not in allowed:
                        continue
                    if cal.name == self._tasks_calendar:
                        continue  # never read our own write calendar
                    try:
                        for ev in cal.date_search(start=start, end=end):
                            vevent = ev.instance.vevent
                            events.append(CalendarEvent(
                                uid=vevent.uid.value,
                                title=vevent.summary.value,
                                start=_to_utc_iso(vevent.dtstart.value),
                                end=_to_utc_iso(vevent.dtend.value),
                            ))
                    except Exception:
                        logger.exception("error fetching events from calendar %s", cal.name)

            logger.info("get_events: %d events for %s", len(events), date)
            return events
        except Exception:
            logger.warning("CalDAV unreachable — returning empty event list")
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_caldav.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/caldav_client.py tests/test_caldav.py
git commit -m "feat: CalDAV client read — get_events with calendar filtering"
```

---

## Task 3: CalDAV Client — Write (Create/Delete Events)

**Files:**
- Modify: `src/timeopt/caldav_client.py`
- Modify: `tests/test_caldav.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_caldav.py`:
```python
def test_create_event_returns_uid():
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal
        mock_tasks_cal = MagicMock()
        type(mock_tasks_cal).name = PropertyMock(return_value="Timeopt")
        mock_principal.calendars.return_value = [mock_tasks_cal]
        created_event = MagicMock()
        created_event.instance.vevent.uid.value = "new-uid-123"
        mock_tasks_cal.save_event.return_value = created_event

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )
        uid = client.create_event(
            title="Fix login bug",
            start="2026-03-28T10:00:00+00:00",
            end="2026-03-28T11:00:00+00:00",
        )
    assert uid == "new-uid-123"


def test_delete_event_calls_caldav():
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal
        mock_tasks_cal = MagicMock()
        type(mock_tasks_cal).name = PropertyMock(return_value="Timeopt")
        mock_principal.calendars.return_value = [mock_tasks_cal]
        mock_event = MagicMock()
        mock_tasks_cal.event_by_uid.return_value = mock_event

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )
        client.delete_event("uid-to-delete")

    mock_tasks_cal.event_by_uid.assert_called_once_with("uid-to-delete")
    mock_event.delete.assert_called_once()


def test_create_tasks_calendar_if_missing():
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal
        # No Timeopt calendar yet
        mock_principal.calendars.return_value = []
        mock_principal.make_calendar.return_value = MagicMock()

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )
        client._ensure_tasks_calendar(mock_principal)

    mock_principal.make_calendar.assert_called_once_with(name="Timeopt")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_caldav.py::test_create_event_returns_uid -v
```

Expected: `AttributeError: 'CalDAVClient' object has no attribute 'create_event'`

- [ ] **Step 3: Add write methods to `caldav_client.py`**

Add to `src/timeopt/caldav_client.py`:
```python
import uuid as _uuid
from icalendar import Calendar, Event as ICALEvent  # type: ignore


def _build_ical(title: str, start: str, end: str, uid: str) -> str:
    cal = Calendar()
    cal.add("prodid", "-//timeopt//EN")
    cal.add("version", "2.0")
    ev = ICALEvent()
    ev.add("summary", title)
    ev.add("dtstart", datetime.fromisoformat(start))
    ev.add("dtend", datetime.fromisoformat(end))
    ev.add("uid", uid)
    cal.add_component(ev)
    return cal.to_ical().decode()


class CalDAVClient:
    # ... (existing __init__ and get_events above) ...

    def _ensure_tasks_calendar(self, principal):
        """Return the Timeopt calendar, creating it if absent."""
        for cal in principal.calendars():
            if cal.name == self._tasks_calendar:
                return cal
        logger.info("creating calendar: %s", self._tasks_calendar)
        return principal.make_calendar(name=self._tasks_calendar)

    def create_event(self, title: str, start: str, end: str) -> str:
        """
        Create a calendar event in the Timeopt calendar.
        Returns the CalDAV UID of the created event.
        """
        uid = str(_uuid.uuid4())
        ical = _build_ical(title, start, end, uid)
        with caldav.DAVClient(
            url=self._url, username=self._username, password=self._password
        ) as client:
            principal = client.principal()
            tasks_cal = self._ensure_tasks_calendar(principal)
            event = tasks_cal.save_event(ical)
            # Some servers return the uid directly; use our generated uid as fallback
            try:
                server_uid = event.instance.vevent.uid.value
            except Exception:
                server_uid = uid
        logger.info("created event: %s uid=%s", title, server_uid)
        return server_uid

    def delete_event(self, caldav_uid: str) -> None:
        """Delete a Timeopt calendar event by its CalDAV UID."""
        try:
            with caldav.DAVClient(
                url=self._url, username=self._username, password=self._password
            ) as client:
                principal = client.principal()
                tasks_cal = self._ensure_tasks_calendar(principal)
                event = tasks_cal.event_by_uid(caldav_uid)
                event.delete()
            logger.info("deleted event uid=%s", caldav_uid)
        except Exception:
            logger.exception("failed to delete event uid=%s", caldav_uid)
```

- [ ] **Step 4: Add `icalendar` dependency**

```bash
uv add icalendar
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_caldav.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/timeopt/caldav_client.py tests/test_caldav.py pyproject.toml uv.lock
git commit -m "feat: CalDAV client write — create/delete events in Timeopt calendar"
```

---

## Task 4: get_dump_templates and resolve_calendar_reference

**Files:**
- Modify: `src/timeopt/core.py`
- Create: `tests/test_core_integrations.py`

- [ ] **Step 1: Write failing tests**

`tests/test_core_integrations.py`:
```python
from timeopt.core import get_dump_templates, resolve_calendar_reference
from timeopt.caldav_client import CalendarEvent


MOCK_EVENTS = [
    CalendarEvent(uid="uid-1", title="Meeting with Jeff",
                  start="2026-03-28T14:00:00+00:00", end="2026-03-28T15:00:00+00:00"),
    CalendarEvent(uid="uid-2", title="Team standup",
                  start="2026-03-28T09:00:00+00:00", end="2026-03-28T09:30:00+00:00"),
]


def test_get_dump_templates_returns_schema_and_templates():
    fragments = ["fix login bug", "call dentist"]
    result = get_dump_templates(fragments, events=[])
    assert "schema" in result
    assert "templates" in result
    assert len(result["templates"]) == 2


def test_get_dump_templates_schema_appears_once():
    fragments = ["task a", "task b", "task c"]
    result = get_dump_templates(fragments, events=[])
    # Schema is a top-level key, NOT inside each template
    for t in result["templates"]:
        assert "priority" not in t or t.get("priority") == "?"
        assert "schema" not in t


def test_get_dump_templates_omits_due_fields_for_simple_tasks():
    result = get_dump_templates(["fix login bug"], events=[])
    tmpl = result["templates"][0]
    assert "due_at" not in tmpl
    assert "due_event_label" not in tmpl


def test_get_dump_templates_includes_due_at_for_time_ref():
    result = get_dump_templates(["deploy before noon"], events=[])
    tmpl = result["templates"][0]
    assert "due_at" in tmpl


def test_get_dump_templates_includes_event_label_for_calendar_ref():
    result = get_dump_templates(["prep report before meeting with Jeff"], events=MOCK_EVENTS)
    tmpl = result["templates"][0]
    assert "due_event_label" in tmpl
    assert tmpl["due_event_label"] == "meeting with Jeff"


def test_get_dump_templates_raw_and_title_prefilled():
    result = get_dump_templates(["fix login bug"], events=[])
    tmpl = result["templates"][0]
    assert tmpl["raw"] == "fix login bug"
    assert tmpl["title"] == "fix login bug"


def test_resolve_calendar_reference_finds_match():
    match = resolve_calendar_reference("meeting with Jeff", MOCK_EVENTS)
    assert match is not None
    assert match["uid"] == "uid-1"
    assert match["score"] >= 70


def test_resolve_calendar_reference_returns_none_for_no_match():
    match = resolve_calendar_reference("board meeting", [])
    assert match is None


def test_resolve_calendar_reference_picks_highest_score():
    match = resolve_calendar_reference("standup", MOCK_EVENTS)
    assert match is not None
    assert "standup" in match["title"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_core_integrations.py -v
```

Expected: `ImportError: cannot import name 'get_dump_templates'`

- [ ] **Step 3: Add `get_dump_templates` and `resolve_calendar_reference` to `core.py`**

Add to `src/timeopt/core.py`:
```python
import re as _re
from rapidfuzz import process as _fuzz_process

# Patterns suggesting an explicit time reference (not a calendar event)
_TIME_PATTERNS = [
    r"\b(before|by|at|until)\s+\d{1,2}(:\d{2})?\s*(am|pm)?\b",
    r"\b(noon|midnight|morning|evening|tonight)\b",
    r"\bby\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\b(today|tomorrow|this week|next week)\b",
    r"\bfor\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
]
_TIME_RE = _re.compile("|".join(_TIME_PATTERNS), _re.IGNORECASE)

# Patterns suggesting a calendar event reference
_EVENT_PATTERNS = [
    r"\b(before|after|during|ahead of|prior to)\s+(?:the\s+)?(?:meeting|call|standup|review|sync|session|presentation|interview|lunch|dinner)\b",
    r"\bbefore\s+(?:my\s+)?(?:meeting|call)\s+with\b",
]
_EVENT_RE = _re.compile("|".join(_EVENT_PATTERNS), _re.IGNORECASE)

_TEMPLATE_SCHEMA = {
    "priority": "high|medium|low",
    "urgent": "bool",
    "category": "work|personal|errands|other",
    "effort": "small|medium|large",
    "due_at": "ISO8601 UTC or omit",
    "due_event_label": "string or omit",
    "due_event_offset_min": "int (negative = before event) or omit",
}


def _extract_event_label(fragment: str) -> str | None:
    """Try to extract the event name from a textual calendar reference."""
    patterns = [
        r"\bbefore\s+(?:my\s+)?(?:meeting\s+with|call\s+with)\s+(.+?)(?:\s*$)",
        r"\b(?:before|after|during|ahead of|prior to)\s+(?:the\s+)?(.+?)(?:\s*$)",
    ]
    for pat in patterns:
        m = _re.search(pat, fragment, _re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def resolve_calendar_reference(
    label: str,
    events: list,
) -> dict | None:
    """
    Fuzzy-match a textual event label against a list of CalendarEvent objects.
    Returns the best match as {uid, title, start, end, score} or None.
    """
    if not events:
        return None
    titles = [ev.title for ev in events]
    results = _fuzz_process.extractOne(label, titles)
    if results is None:
        return None
    title, score, idx = results
    if score < 50:
        return None
    ev = events[idx]
    return {"uid": ev.uid, "title": ev.title, "start": ev.start, "end": ev.end, "score": score}


def get_dump_templates(
    fragments: list[str],
    events: list,
) -> dict:
    """
    Build sparse JSON templates for brain-dump fragments.
    Schema appears once at top level. Only non-null fields included per template.
    events: list of CalendarEvent objects for reference resolution.
    """
    templates = []
    for fragment in fragments:
        tmpl: dict = {
            "raw": fragment,
            "title": fragment.strip(),
            "priority": "?",
            "urgent": "?",
            "category": "?",
            "effort": "?",
        }

        # Detect explicit time reference
        if _TIME_RE.search(fragment):
            tmpl["due_at"] = "?"

        # Detect calendar event reference
        if _EVENT_RE.search(fragment):
            label = _extract_event_label(fragment)
            if label:
                tmpl["due_event_label"] = label
                tmpl["due_event_offset_min"] = "?"
                # Try to resolve now
                match = resolve_calendar_reference(label, events)
                if match:
                    tmpl["_resolved_event_uid"] = match["uid"]

        templates.append(tmpl)

    return {"schema": _TEMPLATE_SCHEMA, "templates": templates}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_core_integrations.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/core.py tests/test_core_integrations.py
git commit -m "feat: get_dump_templates and resolve_calendar_reference"
```

---

## Task 5: dump_task and dump_tasks

**Files:**
- Modify: `src/timeopt/core.py`
- Modify: `tests/test_core_integrations.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_core_integrations.py`:
```python
from timeopt.core import dump_task, dump_tasks, TaskInput


def test_dump_task_saves_and_returns_display_id(conn):
    task = TaskInput(
        title="fix login bug", raw="fix login bug",
        priority="high", urgent=False, category="work", effort="medium"
    )
    display_id = dump_task(conn, task)
    assert display_id.startswith("#1-")
    row = conn.execute("SELECT * FROM tasks WHERE display_id=?", (display_id,)).fetchone()
    assert row is not None


def test_dump_task_auto_classifies(conn):
    from datetime import datetime, timezone, timedelta
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    task = TaskInput(
        title="overdue task", raw="overdue",
        priority="medium", urgent=False,
        category="work", effort="small", due_at=past
    )
    dump_task(conn, task)
    row = conn.execute("SELECT urgent FROM tasks WHERE title='overdue task'").fetchone()
    assert row[0] == 1  # urgency auto-upgraded


def test_dump_task_binds_calendar_event(conn):
    task = TaskInput(
        title="prep report", raw="prep report before meeting with Jeff",
        priority="high", urgent=False, category="work", effort="large",
        due_event_label="meeting with Jeff",
        due_event_uid="uid-1",
        due_event_offset_min=-30,
        due_at="2026-03-28T13:30:00+00:00",
    )
    display_id = dump_task(conn, task)
    row = conn.execute(
        "SELECT due_event_uid, due_unresolved FROM tasks WHERE display_id=?",
        (display_id,)
    ).fetchone()
    assert row["due_event_uid"] == "uid-1"
    assert row["due_unresolved"] == 0


def test_dump_tasks_saves_batch(conn):
    tasks = [
        TaskInput(title="task a", raw="a", priority="high", urgent=False,
                  category="work", effort="small"),
        TaskInput(title="task b", raw="b", priority="low", urgent=False,
                  category="personal", effort="small"),
    ]
    display_ids = dump_tasks(conn, tasks)
    assert len(display_ids) == 2
    count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    assert count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_core_integrations.py::test_dump_task_saves_and_returns_display_id -v
```

Expected: `ImportError: cannot import name 'dump_task'`

- [ ] **Step 3: Add `dump_task` and `dump_tasks` to `core.py`**

Add to `src/timeopt/core.py`:
```python
def dump_task(conn: sqlite3.Connection, task: TaskInput) -> str:
    """
    Save a single task from a filled template.
    Auto-runs Eisenhower classification after insert.
    Returns display_id.
    """
    display_id = create_task(conn, task)
    # Auto-classify: upgrade urgency if overdue
    _auto_classify(conn)
    logger.info("dump_task: saved %s", display_id)
    return display_id


def dump_tasks(conn: sqlite3.Connection, tasks: list[TaskInput]) -> list[str]:
    """
    Save a batch of tasks from filled templates.
    Auto-runs Eisenhower classification once after all inserts.
    Returns list of display_ids.
    """
    display_ids = [create_task(conn, task) for task in tasks]
    _auto_classify(conn)
    logger.info("dump_tasks: saved %d tasks", len(display_ids))
    return display_ids
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_core_integrations.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/core.py tests/test_core_integrations.py
git commit -m "feat: dump_task and dump_tasks with auto-classification"
```

---

## Task 6: push_calendar_blocks (Transactional)

**Files:**
- Modify: `src/timeopt/planner.py`
- Create: `tests/test_push_blocks.py`

- [ ] **Step 1: Write failing tests**

`tests/test_push_blocks.py`:
```python
from unittest.mock import MagicMock
from timeopt.core import create_task, TaskInput
from timeopt.planner import get_plan_proposal, push_calendar_blocks, get_calendar_blocks


def _seed(conn):
    tasks = [
        TaskInput(title="task a", raw="a", priority="high", urgent=True,
                  category="work", effort="small"),
        TaskInput(title="task b", raw="b", priority="medium", urgent=False,
                  category="work", effort="small"),
    ]
    for t in tasks:
        create_task(conn, t)


def test_push_calendar_blocks_saves_to_db(conn):
    _seed(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    caldav = MagicMock()
    caldav.create_event.side_effect = ["uid-1", "uid-2"]
    caldav.delete_event = MagicMock()

    push_calendar_blocks(conn, proposal, date="2026-03-28", caldav_client=caldav)
    blocks = get_calendar_blocks(conn, "2026-03-28")
    assert len(blocks) == len(proposal["blocks"])


def test_push_calendar_blocks_replaces_existing(conn):
    _seed(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")

    caldav = MagicMock()
    caldav.create_event.side_effect = ["uid-old-1", "uid-old-2"]
    push_calendar_blocks(conn, proposal, date="2026-03-28", caldav_client=caldav)

    # Re-push same date
    caldav2 = MagicMock()
    caldav2.create_event.side_effect = ["uid-new-1", "uid-new-2"]
    caldav2.delete_event = MagicMock()
    push_calendar_blocks(conn, proposal, date="2026-03-28", caldav_client=caldav2)

    blocks = get_calendar_blocks(conn, "2026-03-28")
    uids = {b["caldav_uid"] for b in blocks}
    assert "uid-new-1" in uids
    assert "uid-old-1" not in uids
    # delete was called for old uids
    caldav2.delete_event.assert_called()


def test_push_calendar_blocks_aborts_on_caldav_failure(conn):
    import pytest
    _seed(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")

    caldav = MagicMock()
    caldav.create_event.side_effect = Exception("CalDAV write failed")

    with pytest.raises(Exception, match="CalDAV write failed"):
        push_calendar_blocks(conn, proposal, date="2026-03-28", caldav_client=caldav)

    # DB must be untouched — no blocks saved
    blocks = get_calendar_blocks(conn, "2026-03-28")
    assert blocks == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_push_blocks.py -v
```

Expected: `ImportError: cannot import name 'push_calendar_blocks'`

- [ ] **Step 3: Add `push_calendar_blocks` to `planner.py`**

Add to `src/timeopt/planner.py`:
```python
def push_calendar_blocks(
    conn: sqlite3.Connection,
    proposal: dict,
    date: str,
    caldav_client,
) -> None:
    """
    Transactional push: all CalDAV writes collected first,
    SQLite committed only on full success.
    If CalDAV fails, raises and leaves DB unchanged.
    """
    blocks = proposal["blocks"]
    if not blocks:
        logger.info("push_calendar_blocks: no blocks to push for %s", date)
        return

    # Step 1: collect old UIDs that need deletion (from DB)
    old_uids = delete_calendar_blocks_for_date.__wrapped__(conn, date) \
        if hasattr(delete_calendar_blocks_for_date, "__wrapped__") \
        else _get_uids_for_date(conn, date)

    # Step 2: attempt ALL CalDAV creates first (may raise)
    new_uids = []
    for block in blocks:
        end_dt = (
            datetime.fromisoformat(block["start"]) +
            timedelta(minutes=block["duration_min"])
        ).isoformat()
        uid = caldav_client.create_event(
            title=block["title"],
            start=block["start"],
            end=end_dt,
        )
        new_uids.append(uid)

    # Step 3: all creates succeeded — delete old CalDAV events
    for uid in old_uids:
        caldav_client.delete_event(uid)

    # Step 4: commit SQLite atomically
    conn.execute("DELETE FROM calendar_blocks WHERE plan_date=?", (date,))
    for block, uid in zip(blocks, new_uids):
        conn.execute(
            "INSERT INTO calendar_blocks(id, task_id, caldav_uid, scheduled_at, duration_min, plan_date) "
            "VALUES (?,?,?,?,?,?)",
            (str(_uuid.uuid4()), block["task_id"], uid, block["start"], block["duration_min"], date),
        )
    conn.commit()
    logger.info("push_calendar_blocks: pushed %d blocks for %s", len(blocks), date)


def _get_uids_for_date(conn: sqlite3.Connection, date: str) -> list[str]:
    rows = conn.execute(
        "SELECT caldav_uid FROM calendar_blocks WHERE plan_date=?", (date,)
    ).fetchall()
    return [row[0] for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_push_blocks.py -v
```

Expected: all pass.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/timeopt/planner.py tests/test_push_blocks.py
git commit -m "feat: push_calendar_blocks with transactional CalDAV + SQLite semantics"
```

---

## Task 7: /sync — Algorithmic + Claude-Triggered

**Files:**
- Modify: `src/timeopt/core.py`
- Create: `tests/test_sync.py`

- [ ] **Step 1: Write failing tests**

`tests/test_sync.py`:
```python
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta
from timeopt.core import (
    create_task, TaskInput, sync_bound_tasks, get_unresolved_tasks
)
from timeopt.caldav_client import CalendarEvent


def _bound_task(conn, due_event_uid="uid-jeff", due_at="2026-03-28T13:30:00+00:00"):
    task = TaskInput(
        title="prep report", raw="prep before meeting with Jeff",
        priority="high", urgent=False, category="work", effort="large",
        due_at=due_at,
        due_event_uid=due_event_uid,
        due_event_label="meeting with Jeff",
        due_event_offset_min=-30,
    )
    return create_task(conn, task)


def test_sync_bound_tasks_updates_due_at(conn):
    display_id = _bound_task(conn)
    # Event has moved to Thursday
    updated_events = [
        CalendarEvent(
            uid="uid-jeff",
            title="Meeting with Jeff",
            start="2026-03-30T14:00:00+00:00",  # moved
            end="2026-03-30T15:00:00+00:00",
        )
    ]
    changes = sync_bound_tasks(conn, updated_events)
    assert len(changes) == 1
    assert changes[0]["display_id"] == display_id
    row = conn.execute(
        "SELECT due_at FROM tasks WHERE display_id=?", (display_id,)
    ).fetchone()
    # due_at should be 30 min before new event start
    assert "2026-03-30T13:30" in row[0]


def test_sync_bound_tasks_warns_if_event_deleted(conn):
    display_id = _bound_task(conn)
    # Event no longer in calendar
    changes = sync_bound_tasks(conn, events=[])
    # Task's due_at preserved, but change flagged as "event_missing"
    assert any(c["status"] == "event_missing" for c in changes)


def test_sync_bound_tasks_ignores_non_bound(conn):
    task = TaskInput(
        title="unbound task", raw="unbound",
        priority="low", urgent=False, category="other", effort="small",
        due_at="2026-03-28T10:00:00+00:00",
    )
    create_task(conn, task)
    changes = sync_bound_tasks(conn, events=[])
    assert len(changes) == 0  # non-bound task not touched


def test_get_unresolved_tasks_returns_due_unresolved(conn):
    task = TaskInput(
        title="board meeting prep", raw="prep before board meeting",
        priority="high", urgent=False, category="work", effort="large",
        due_event_label="board meeting",
        due_unresolved=True,
    )
    display_id = create_task(conn, task)
    unresolved = get_unresolved_tasks(conn)
    assert any(t["display_id"] == display_id for t in unresolved)


def test_sync_resolves_unresolved_when_event_appears(conn):
    task = TaskInput(
        title="board meeting prep", raw="prep before board meeting",
        priority="high", urgent=False, category="work", effort="large",
        due_event_label="board meeting",
        due_unresolved=True,
    )
    display_id = create_task(conn, task)
    events = [
        CalendarEvent(
            uid="uid-board",
            title="Board Meeting",
            start="2026-04-15T10:00:00+00:00",
            end="2026-04-15T11:00:00+00:00",
        )
    ]
    from timeopt.core import try_resolve_unresolved
    resolved = try_resolve_unresolved(conn, events)
    assert len(resolved) == 1
    row = conn.execute("SELECT due_unresolved, due_event_uid FROM tasks WHERE display_id=?",
                       (display_id,)).fetchone()
    assert row["due_unresolved"] == 0
    assert row["due_event_uid"] == "uid-board"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sync.py -v
```

Expected: `ImportError: cannot import name 'sync_bound_tasks'`

- [ ] **Step 3: Add sync functions to `core.py`**

Add to `src/timeopt/core.py`:
```python
def sync_bound_tasks(conn: sqlite3.Connection, events: list) -> list[dict]:
    """
    Algorithmic sync: update due_at for bound tasks based on current calendar events.
    Returns list of changes: {display_id, old_due_at, new_due_at, status}
    status: "updated" | "event_missing"
    Only touches tasks with due_event_uid set.
    """
    rows = conn.execute(
        "SELECT id, display_id, due_event_uid, due_event_offset_min, due_at "
        "FROM tasks WHERE due_event_uid IS NOT NULL AND status IN ('pending','delegated')"
    ).fetchall()

    if not rows:
        return []

    events_by_uid = {ev.uid: ev for ev in events}
    changes = []

    for row in rows:
        uid = row["due_event_uid"]
        offset = row["due_event_offset_min"] or 0

        if uid not in events_by_uid:
            changes.append({
                "display_id": row["display_id"],
                "old_due_at": row["due_at"],
                "new_due_at": row["due_at"],  # preserved
                "status": "event_missing",
            })
            continue

        ev = events_by_uid[uid]
        event_start = datetime.fromisoformat(ev.start.replace("Z", "+00:00"))
        new_due_at = (event_start + timedelta(minutes=offset)).isoformat()

        if new_due_at != row["due_at"]:
            conn.execute(
                "UPDATE tasks SET due_at=? WHERE id=?", (new_due_at, row["id"])
            )
            changes.append({
                "display_id": row["display_id"],
                "old_due_at": row["due_at"],
                "new_due_at": new_due_at,
                "status": "updated",
            })

    conn.commit()
    logger.info("sync_bound_tasks: %d changes", len(changes))
    return changes


def get_unresolved_tasks(conn: sqlite3.Connection) -> list[dict]:
    """Return tasks with due_unresolved=True."""
    rows = conn.execute(
        "SELECT id, display_id, due_event_label FROM tasks "
        "WHERE due_unresolved=1 AND status IN ('pending','delegated')"
    ).fetchall()
    return [dict(row) for row in rows]


def try_resolve_unresolved(conn: sqlite3.Connection, events: list) -> list[dict]:
    """
    Attempt to bind unresolved tasks to calendar events.
    Returns list of {display_id, status: "resolved" | "still_unresolved"}.
    """
    unresolved = get_unresolved_tasks(conn)
    results = []
    for task in unresolved:
        label = task["due_event_label"]
        if not label:
            continue
        match = resolve_calendar_reference(label, events)
        if match:
            event_start = datetime.fromisoformat(
                match["start"].replace("Z", "+00:00")
            )
            # Use offset -30 as default if not stored
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

- [ ] **Step 4: Run all tests to verify they pass**

```bash
uv run pytest -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/timeopt/core.py tests/test_sync.py
git commit -m "feat: /sync — algorithmic event binding update + unresolved task re-binding"
```

---

## Self-Review

### Spec Coverage

| Spec requirement | Covered by |
|---|---|
| LLM abstraction (Anthropic + OpenAI-compat) | Task 1 |
| CalDAV read with calendar filtering | Task 2 |
| CalDAV write (create/delete events) | Task 3 |
| Auto-create Timeopt calendar | Task 3 |
| `get_dump_templates` sparse + schema-once | Task 4 |
| `resolve_calendar_reference` via rapidfuzz | Task 4 |
| `dump_task` + `dump_tasks` with auto-classify | Task 5 |
| `push_calendar_blocks` transactional | Task 6 |
| `/sync` algorithmic (bound events) | Task 7 |
| `/sync` Claude-triggered (unresolved) | Task 7 |
| CalDAV unreachable → empty, no crash | Task 2 |
| Event deleted → warn, preserve due_at | Task 7 |

### No Placeholders
Verified: all code blocks complete with real implementations.

### Type Consistency
- `CalendarEvent` dataclass defined in Task 2, consumed in Tasks 4, 7
- `get_dump_templates` returns `{schema, templates}` — consistent with spec
- `push_calendar_blocks` consumes `proposal["blocks"]` from `get_plan_proposal` — keys match
