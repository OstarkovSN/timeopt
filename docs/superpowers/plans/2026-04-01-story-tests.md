# User Story E2E Tests — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `tests/test_e2e_stories.py` with 5 async e2e tests that script the exact MCP tool-call sequences Claude would execute for each user story from the design spec.

**Architecture:** Each test opens a real `timeopt-server` subprocess via `stdio_client`, makes tool calls in the order Claude would during a real user session, and asserts observable state at each step. No LLM involved — Claude's decisions are scripted deterministically. Stories 1/3/5 seed data through MCP tool calls (fully e2e); Stories 2/4 seed directly into SQLite for precise Eisenhower ordering control.

**Tech Stack:** `pytest`, `pytest-asyncio` (`asyncio_mode = "auto"`), `mcp.client.stdio.stdio_client`, `mcp.ClientSession`, `timeopt.db.get_connection`, `timeopt.core.dump_task/TaskInput`

---

## Files

- **Create:** `tests/test_e2e_stories.py` — 5 story tests, `@pytest.mark.e2e`
- **No other files modified** — existing test infrastructure (pyproject.toml markers, asyncio_mode) is already in place from the e2e plan

---

## Source Stories

Extracted from `docs/superpowers/specs/2026-03-26-timeopt-design.md` § "User Stories":

| Test | Story | Tool-call sequence |
|---|---|---|
| `test_story_brain_dump` | Brain Dump | `get_dump_templates` → `dump_tasks` → `list_tasks` |
| `test_story_view_tasks_sort_order` | View Tasks | seed Q1–Q4 → `list_tasks` → assert order → `mark_delegated` |
| `test_story_mark_done` | Mark Done | `dump_task` × 2 → `fuzzy_match_tasks` × 2 → `mark_done` → `list_tasks` |
| `test_story_daily_plan` | Daily Plan | seed Q1+Q2 → `get_plan_proposal` → assert Q1 before Q2 |
| `test_story_delegation_lifecycle` | Delegation | `dump_task` → `classify_tasks` → `mark_delegated` → `update_task_notes` → `return_to_pending` → `get_task` |

---

### Task 1: File scaffold with shared helpers

**Files:**
- Create: `tests/test_e2e_stories.py`

- [ ] **Step 1: Create the file with imports and helpers**

```python
"""E2E story tests — scripted MCP tool-call sequences for each user story."""
import json
import os

import pytest

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

from timeopt.db import get_connection, create_schema
from timeopt.core import dump_task, TaskInput

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _server_params(db_path: str) -> StdioServerParameters:
    return StdioServerParameters(
        command="uv",
        args=["run", "timeopt-server"],
        env={**os.environ, "TIMEOPT_DB": db_path},
        cwd=PROJECT_ROOT,
    )


def _call(result) -> dict:
    return json.loads(result.content[0].text)
```

- [ ] **Step 2: Verify file is collected**

Run: `uv run pytest --collect-only -m e2e tests/test_e2e_stories.py -q`

Expected output: `no tests ran` (no tests defined yet, but file imports without error)

---

### Task 2: Story 1 — Brain Dump

**Files:**
- Modify: `tests/test_e2e_stories.py`

- [ ] **Step 1: Add the test**

Append to `tests/test_e2e_stories.py`:

```python
@pytest.mark.e2e
async def test_story_brain_dump(tmp_path):
    """Brain Dump Parser story: get_dump_templates → dump_tasks → list shows all 4 tasks in Eisenhower order."""
    params = _server_params(str(tmp_path / "e2e.db"))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()

            # Step 1 — Claude calls get_dump_templates with the raw fragments
            fragments = [
                "fix login bug",
                "call dentist",
                "deploy hotfix before noon",
                "prep slides for thursday",
            ]
            templates = _call(await session.call_tool("get_dump_templates", {"fragments": fragments}))
            assert "schema" in templates
            assert "templates" in templates
            assert len(templates["templates"]) == 4
            for t in templates["templates"]:
                assert "raw" in t
                assert "title" in t

            # Step 2 — Claude fills each template and submits as a batch
            result = _call(await session.call_tool("dump_tasks", {"tasks": [
                {"raw": "fix login bug",             "title": "fix login bug",             "priority": "high",   "urgent": False, "category": "work",     "effort": "medium"},
                {"raw": "call dentist",              "title": "call dentist",              "priority": "medium", "urgent": False, "category": "personal", "effort": "small"},
                {"raw": "deploy hotfix before noon", "title": "deploy hotfix before noon", "priority": "high",   "urgent": True,  "category": "work",     "effort": "medium"},
                {"raw": "prep slides for thursday",  "title": "prep slides for thursday",  "priority": "high",   "urgent": False, "category": "work",     "effort": "large"},
            ]}))
            assert result["count"] == 4
            assert len(result["display_ids"]) == 4

            # Step 3 — list_tasks: all 4 present, Q1 (urgent+high) is first
            listed = _call(await session.call_tool("list_tasks", {}))
            assert len(listed["tasks"]) == 4
            titles = [t["title"] for t in listed["tasks"]]
            assert "fix login bug" in titles
            assert "call dentist" in titles
            assert "deploy hotfix before noon" in titles
            assert "prep slides for thursday" in titles
            # Q1 task (urgent + high) must come before all others
            assert listed["tasks"][0]["title"] == "deploy hotfix before noon"
            assert listed["tasks"][0]["urgent"] is True
```

- [ ] **Step 2: Run and verify it passes**

Run: `uv run pytest -m e2e tests/test_e2e_stories.py::test_story_brain_dump -v`

Expected: `PASSED`

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_stories.py
git commit -m "tests(stories): scaffold + Story 1 Brain Dump"
```

---

### Task 3: Story 2 — View Tasks sort order

**Files:**
- Modify: `tests/test_e2e_stories.py`

- [ ] **Step 1: Add the test**

Append to `tests/test_e2e_stories.py`:

```python
@pytest.mark.e2e
async def test_story_view_tasks_sort_order(tmp_path):
    """View Tasks story: list_tasks returns Q1→Q2→Q3→Q4 order; delegated task shown with correct status."""
    db_path = str(tmp_path / "e2e.db")
    conn = get_connection(db_path)
    create_schema(conn)
    dump_task(conn, TaskInput(title="fix critical outage",   raw="fix critical outage",   priority="high", urgent=True,  category="work", effort="medium"))  # Q1
    dump_task(conn, TaskInput(title="write quarterly report", raw="write quarterly report", priority="high", urgent=False, category="work", effort="large"))   # Q2
    dump_task(conn, TaskInput(title="reply to newsletter",   raw="reply to newsletter",   priority="low",  urgent=True,  category="work", effort="small"))    # Q3
    dump_task(conn, TaskInput(title="clean up old files",    raw="clean up old files",    priority="low",  urgent=False, category="work", effort="small"))    # Q4
    conn.close()

    params = _server_params(db_path)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()

            # Step 1 — list_tasks returns tasks in Eisenhower order Q1→Q2→Q3→Q4
            listed = _call(await session.call_tool("list_tasks", {}))
            assert len(listed["tasks"]) == 4
            titles = [t["title"] for t in listed["tasks"]]
            assert titles[0] == "fix critical outage"        # Q1 first
            assert titles[-1] == "clean up old files"        # Q4 last
            q2_idx = titles.index("write quarterly report")
            q3_idx = titles.index("reply to newsletter")
            assert q2_idx < q3_idx                           # Q2 before Q3

            # Step 2 — delegate the Q3 task (as Claude's /check-urgent would)
            candidates = _call(await session.call_tool("fuzzy_match_tasks", {"query": "reply to newsletter"}))
            task_uuid = candidates["candidates"][0]["task_id"]
            assert _call(await session.call_tool("mark_delegated", {"task_id": task_uuid})) == {"ok": True}

            # Step 3 — list_tasks shows delegated status; only 3 pending remain
            listed2 = _call(await session.call_tool("list_tasks", {}))
            statuses = {t["title"]: t["status"] for t in listed2["tasks"]}
            assert statuses["reply to newsletter"] == "delegated"
            pending_count = sum(1 for t in listed2["tasks"] if t["status"] == "pending")
            assert pending_count == 3
```

- [ ] **Step 2: Run and verify it passes**

Run: `uv run pytest -m e2e tests/test_e2e_stories.py::test_story_view_tasks_sort_order -v`

Expected: `PASSED`

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_stories.py
git commit -m "tests(stories): Story 2 View Tasks sort order"
```

---

### Task 4: Story 3 — Mark Done

**Files:**
- Modify: `tests/test_e2e_stories.py`

- [ ] **Step 1: Add the test**

Append to `tests/test_e2e_stories.py`:

```python
@pytest.mark.e2e
async def test_story_mark_done(tmp_path):
    """Mark Done story: fuzzy_match_tasks resolves queries → mark_done → pending list empty."""
    params = _server_params(str(tmp_path / "e2e.db"))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()

            # Seed two tasks via MCP (fully e2e)
            _call(await session.call_tool("dump_task", {"task": {
                "title": "fix login bug", "priority": "high", "urgent": False,
                "category": "work", "effort": "medium",
            }}))
            _call(await session.call_tool("dump_task", {"task": {
                "title": "prep slides for thursday", "priority": "high", "urgent": False,
                "category": "work", "effort": "large",
            }}))

            # Step 1 — fuzzy match "fix login" → high-confidence hit
            m1 = _call(await session.call_tool("fuzzy_match_tasks", {"query": "fix login"}))
            assert len(m1["candidates"]) > 0
            assert m1["candidates"][0]["score"] >= 80
            uuid_1 = m1["candidates"][0]["task_id"]

            # Step 2 — fuzzy match "prep slides" → high-confidence hit
            m2 = _call(await session.call_tool("fuzzy_match_tasks", {"query": "prep slides"}))
            assert len(m2["candidates"]) > 0
            assert m2["candidates"][0]["score"] >= 80
            uuid_2 = m2["candidates"][0]["task_id"]

            # Step 3 — mark both done in one call
            done = _call(await session.call_tool("mark_done", {"task_ids": [uuid_1, uuid_2]}))
            assert done == {"ok": True}

            # Step 4 — pending list is now empty
            pending = _call(await session.call_tool("list_tasks", {"status": "pending"}))
            assert pending["tasks"] == []
```

- [ ] **Step 2: Run and verify it passes**

Run: `uv run pytest -m e2e tests/test_e2e_stories.py::test_story_mark_done -v`

Expected: `PASSED`

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_stories.py
git commit -m "tests(stories): Story 3 Mark Done"
```

---

### Task 5: Story 4 — Daily Plan

**Files:**
- Modify: `tests/test_e2e_stories.py`

- [ ] **Step 1: Add the test**

Append to `tests/test_e2e_stories.py`:

```python
@pytest.mark.e2e
async def test_story_daily_plan(tmp_path):
    """Daily Plan story: get_plan_proposal returns Q1 block scheduled before Q2 block."""
    db_path = str(tmp_path / "e2e.db")
    conn = get_connection(db_path)
    create_schema(conn)
    dump_task(conn, TaskInput(title="fix critical outage",    raw="fix critical outage",    priority="high", urgent=True,  category="work", effort="medium"))  # Q1
    dump_task(conn, TaskInput(title="write quarterly report", raw="write quarterly report", priority="high", urgent=False, category="work", effort="medium"))  # Q2
    conn.close()

    params = _server_params(db_path)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()

            result = _call(await session.call_tool("get_plan_proposal", {"date": "2026-04-02"}))
            assert "blocks" in result
            blocks = result["blocks"]
            assert len(blocks) >= 2

            # Each block has required fields
            required_keys = {"task_id", "display_id", "title", "start", "duration_min", "quadrant"}
            for block in blocks:
                assert required_keys <= block.keys(), f"block missing keys: {required_keys - block.keys()}"

            # Q1 block must come before Q2 block
            q1_idx = next(i for i, b in enumerate(blocks) if b["quadrant"] == "Q1")
            q2_idx = next(i for i, b in enumerate(blocks) if b["quadrant"] == "Q2")
            assert q1_idx < q2_idx
```

- [ ] **Step 2: Run and verify it passes**

Run: `uv run pytest -m e2e tests/test_e2e_stories.py::test_story_daily_plan -v`

Expected: `PASSED`

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_stories.py
git commit -m "tests(stories): Story 4 Daily Plan block ordering"
```

---

### Task 6: Story 5 — Delegation Lifecycle

**Files:**
- Modify: `tests/test_e2e_stories.py`

- [ ] **Step 1: Add the test**

Append to `tests/test_e2e_stories.py`:

```python
@pytest.mark.e2e
async def test_story_delegation_lifecycle(tmp_path):
    """Delegation story (failure path): Q3 task → delegated → progress note → returned to pending with notes."""
    params = _server_params(str(tmp_path / "e2e.db"))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()

            # Step 1 — dump a Q3 task (urgent + low priority)
            dumped = _call(await session.call_tool("dump_task", {"task": {
                "title": "reply to accountant",
                "priority": "low",
                "urgent": True,
                "category": "work",
                "effort": "small",
            }}))
            task_uuid = dumped["id"]

            # Step 2 — classify_tasks identifies it as Q3
            classified = _call(await session.call_tool("classify_tasks", {}))
            quadrants = {t["id"]: t["quadrant"] for t in classified["tasks"]}
            assert quadrants[task_uuid] == "Q3"

            # Step 3 — main Claude delegates it
            assert _call(await session.call_tool("mark_delegated", {"task_id": task_uuid})) == {"ok": True}
            listed = _call(await session.call_tool("list_tasks", {}))
            task_entry = next(t for t in listed["tasks"] if t["title"] == "reply to accountant")
            assert task_entry["status"] == "delegated"

            # Step 4 — Delegation Executor writes a progress note
            assert _call(await session.call_tool("update_task_notes", {
                "task_id": task_uuid,
                "notes": "Attempting to send email via mail tool",
            })) == {"ok": True}

            # Step 5 — Executor fails and returns task to pending
            assert _call(await session.call_tool("return_to_pending", {
                "task_id": task_uuid,
                "notes": "No email tool available",
            })) == {"ok": True}

            # Step 6 — task is back in pending with both notes visible
            pending = _call(await session.call_tool("list_tasks", {"status": "pending"}))
            assert any(t["title"] == "reply to accountant" for t in pending["tasks"])

            detail = _call(await session.call_tool("get_task", {"task_id": task_uuid}))
            assert detail["status"] == "pending"
            assert "Attempting to send email via mail tool" in detail["notes"]
            assert "No email tool available" in detail["notes"]
```

- [ ] **Step 2: Run and verify it passes**

Run: `uv run pytest -m e2e tests/test_e2e_stories.py::test_story_delegation_lifecycle -v`

Expected: `PASSED`

- [ ] **Step 3: Run the full story suite**

Run: `uv run pytest -m e2e tests/test_e2e_stories.py -v`

Expected: `5 passed`

- [ ] **Step 4: Verify default run is unaffected**

Run: `uv run pytest tests/ -q`

Expected: `196 passed, 18 deselected` (13 existing e2e + 5 new story e2e, all excluded by default)

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_stories.py
git commit -m "tests(stories): Story 5 Delegation lifecycle + full suite smoke"
```

---

## Self-Review

**Spec coverage:**
- Brain Dump story → Task 2 ✅ (get_dump_templates → dump_tasks → list order)
- View Tasks story → Task 3 ✅ (Eisenhower order, delegated status)
- Mark Done story → Task 4 ✅ (fuzzy match → mark_done → empty pending)
- Daily Plan story → Task 5 ✅ (Q1 before Q2 in blocks)
- Check Urgent/Delegation story → Task 6 ✅ (classify Q3 → delegate → notes → return_to_pending)

**Spec items intentionally out of scope:**
- Playwright TUI assertions — spec says "Playwright MCP drives Claude Code TUI" but that requires a live Claude Code session; replaced by direct MCP protocol assertions which test the same underlying behavior
- `push_calendar_blocks` in Story 4 — requires live CalDAV; already covered with mocks in `test_push_blocks.py`
- Ambiguous fuzzy-match path in Story 3 — requires two close-scoring tasks; covered in `test_server.py::test_fuzzy_match_tasks_ambiguous`

**Placeholder scan:** No TBD/TODO/placeholder patterns found. All steps contain complete code.

**Type consistency:**
- `_call(result) -> dict` — used consistently across all tasks
- `_server_params(db_path: str)` — used consistently across all tasks
- `classified["tasks"][i]["id"]` — matches `test_server.py::test_classify_tasks` which confirms tasks have `"id"` key
- `dumped["id"]` — matches server `dump_task` return shape `{"display_id": str, "id": uuid_str}` (verified from `test_e2e_server.py::test_dump_and_list`)
- `listed["tasks"][i]["status"]` — `list_tasks` returns full task dicts including `status` field
