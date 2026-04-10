"""E2E tests for the timeopt MCP server — real stdio JSON-RPC via mcp client."""
import json
import os

import pytest

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

from timeopt.db import get_connection, create_schema
from timeopt.core import dump_task, TaskInput

import os as _os
PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))

EXPECTED_TOOLS = {
    "list_tasks", "get_task", "fuzzy_match_tasks", "dump_task",
    "mark_done", "mark_delegated", "update_task_notes", "return_to_pending",
    "classify_tasks", "get_config", "set_config", "get_dump_templates",
    "dump_tasks", "resolve_calendar_reference", "get_calendar_events",
    "get_plan_proposal", "push_calendar_blocks", "sync_calendar",
}


def _server_params(db_path: str) -> StdioServerParameters:
    return StdioServerParameters(
        command="uv",
        args=["run", "timeopt-server"],
        env={**os.environ, "TIMEOPT_DB": db_path},
        cwd=PROJECT_ROOT,
    )


def _call(result) -> dict:
    return json.loads(result.content[0].text)


@pytest.mark.e2e
async def test_server_lists_tools(tmp_path):
    """Server exposes exactly the expected 18 tools."""
    params = _server_params(str(tmp_path / "e2e.db"))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            assert tool_names == EXPECTED_TOOLS


@pytest.mark.e2e
async def test_list_tasks_empty(tmp_path):
    """list_tasks on empty DB returns {tasks: []}."""
    params = _server_params(str(tmp_path / "e2e.db"))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool("list_tasks", {})
            data = _call(result)
            assert data == {"tasks": []}


@pytest.mark.e2e
async def test_dump_and_list(tmp_path):
    """dump_task then list_tasks shows the task."""
    params = _server_params(str(tmp_path / "e2e.db"))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            dumped = _call(await session.call_tool("dump_task", {
                "task": {
                    "title": "write report",
                    "priority": "high",
                    "urgent": False,
                    "category": "work",
                    "effort": "medium",
                }
            }))
            assert "display_id" in dumped
            assert "id" in dumped

            tasks = _call(await session.call_tool("list_tasks", {}))
            titles = [t["title"] for t in tasks["tasks"]]
            assert "write report" in titles


@pytest.mark.e2e
async def test_mark_done_flow(tmp_path):
    """dump → mark_done → list_tasks(pending) is empty."""
    params = _server_params(str(tmp_path / "e2e.db"))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            dumped = _call(await session.call_tool("dump_task", {
                "task": {"title": "finish docs", "priority": "medium",
                         "urgent": False, "category": "work", "effort": "small"}
            }))
            task_uuid = dumped["id"]

            done = _call(await session.call_tool("mark_done", {"task_ids": [task_uuid]}))
            assert done == {"ok": True}

            pending = _call(await session.call_tool("list_tasks", {"status": "pending"}))
            assert pending["tasks"] == []


@pytest.mark.e2e
async def test_get_config(tmp_path):
    """get_config(day_start) returns default value 09:00."""
    params = _server_params(str(tmp_path / "e2e.db"))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = _call(await session.call_tool("get_config", {"key": "day_start"}))
            assert result["key"] == "day_start"
            assert result["value"] == "09:00"


@pytest.mark.e2e
async def test_get_calendar_events_no_caldav(tmp_path):
    """get_calendar_events without CalDAV configured returns warning, not error."""
    params = _server_params(str(tmp_path / "e2e.db"))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = _call(await session.call_tool("get_calendar_events", {}))
            assert "warning" in result
            assert "events" in result
            assert result["events"] == []


@pytest.mark.e2e
async def test_get_plan_proposal(tmp_path):
    """Seeded tasks produce non-empty blocks from get_plan_proposal."""
    db_path = str(tmp_path / "e2e.db")
    conn = get_connection(db_path)
    create_schema(conn)
    dump_task(conn, TaskInput(
        title="design database schema",
        raw="design database schema",
        priority="high",
        urgent=False,
        category="work",
        effort="medium",
    ))
    conn.close()

    params = _server_params(db_path)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = _call(await session.call_tool("get_plan_proposal", {"date": "2026-04-01"}))
            assert "blocks" in result
            assert len(result["blocks"]) > 0
