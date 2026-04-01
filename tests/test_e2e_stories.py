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
