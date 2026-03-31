import logging
import os
from datetime import date as _date_type, datetime as _datetime
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

from timeopt import core, db, planner
from timeopt.caldav_client import CalDAVClient
from timeopt.core import TaskInput

logger = logging.getLogger(__name__)
mcp = FastMCP("timeopt")

_DEFAULT_DB = str(Path.home() / ".timeopt" / "tasks.db")


def _db_path() -> str:
    return os.environ.get("TIMEOPT_DB", _DEFAULT_DB)


def _open_conn():
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = db.get_connection(path)
    db.create_schema(conn)
    return conn


def _parse_date(date_str: Optional[str]) -> _date_type:
    if date_str:
        return _datetime.fromisoformat(date_str).date()
    return _date_type.today()


def _get_caldav(conn) -> Optional[CalDAVClient]:
    url = core.get_config(conn, "caldav_url") or "https://caldav.yandex.ru"
    username = core.get_config(conn, "caldav_username")
    password = core.get_config(conn, "caldav_password")
    read_cals = core.get_config(conn, "caldav_read_calendars") or "all"
    tasks_cal = core.get_config(conn, "caldav_tasks_calendar") or "Timeopt"
    if not username or not password:
        return None
    return CalDAVClient(
        url=url, username=username, password=password,
        read_calendars=read_cals, tasks_calendar=tasks_cal,
    )


def _dict_to_task_input(d: dict) -> TaskInput:
    return TaskInput(
        title=d.get("title", ""),
        raw=d.get("raw") or d.get("title", ""),
        priority=d.get("priority", "medium"),
        urgent=bool(d.get("urgent", False)),
        category=d.get("category", "other"),
        effort=d.get("effort") or None,
        due_at=d.get("due_at"),
        due_event_label=d.get("due_event_label"),
        due_event_uid=d.get("due_event_uid") or d.get("_resolved_event_uid"),
        due_event_offset_min=d.get("due_event_offset_min"),
        due_unresolved=bool(d.get("due_unresolved", False)),
    )


@mcp.tool()
def list_tasks(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    include_old_done: bool = False,
) -> dict:
    """List tasks. Defaults to pending + delegated, sorted by Eisenhower quadrant."""
    conn = _open_conn()
    try:
        tasks = core.list_tasks(conn, status=status, priority=priority,
                                category=category, include_old_done=include_old_done)
        return {"tasks": tasks}
    finally:
        conn.close()


@mcp.tool()
def get_task(task_id: str) -> dict:
    """Get full detail for a single task by UUID. Requires UUID — use fuzzy_match_tasks to find UUID first."""
    conn = _open_conn()
    try:
        try:
            return core.get_task(conn, task_id)
        except ValueError as e:
            return {"error": str(e)}
    finally:
        conn.close()


@mcp.tool()
def fuzzy_match_tasks(query: str) -> dict:
    """Fuzzy-match active task titles. Returns ranked candidates with scores."""
    conn = _open_conn()
    try:
        candidates = core.fuzzy_match_tasks(conn, query)
        return {"candidates": candidates}
    finally:
        conn.close()


@mcp.tool()
def dump_task(task: dict) -> dict:
    """Save a new task. Returns display_id and UUID."""
    conn = _open_conn()
    try:
        task_input = _dict_to_task_input(task)
        display_id = core.dump_task(conn, task_input)
        row = conn.execute(
            "SELECT id FROM tasks WHERE display_id=?", (display_id,)
        ).fetchone()
        return {"display_id": display_id, "id": row["id"] if row else None}
    finally:
        conn.close()


@mcp.tool()
def mark_done(task_ids: list) -> dict:
    """Mark tasks as done. Accepts list of UUIDs or display_ids."""
    conn = _open_conn()
    try:
        try:
            core.mark_done(conn, task_ids)
            return {"ok": True}
        except ValueError as e:
            return {"error": str(e)}
    finally:
        conn.close()


@mcp.tool()
def mark_delegated(task_id: str, notes: Optional[str] = None) -> dict:
    """Set task status to delegated. Optionally write an initial timestamped note."""
    conn = _open_conn()
    try:
        try:
            core.mark_delegated(conn, task_id, notes)
            return {"ok": True}
        except ValueError as e:
            return {"error": str(e)}
    finally:
        conn.close()


@mcp.tool()
def update_task_notes(task_id: str, notes: str) -> dict:
    """Append a timestamped note to a delegated task. Returns error if task is not delegated."""
    conn = _open_conn()
    try:
        try:
            core.update_task_notes(conn, task_id, notes)
            return {"ok": True}
        except ValueError as e:
            return {"error": str(e)}
    finally:
        conn.close()


@mcp.tool()
def return_to_pending(task_id: str, notes: str) -> dict:
    """Return a delegated task to pending with a failure note."""
    conn = _open_conn()
    try:
        try:
            core.return_to_pending(conn, task_id, notes)
            return {"ok": True}
        except ValueError as e:
            return {"error": str(e)}
    finally:
        conn.close()


@mcp.tool()
def classify_tasks(task_ids: Optional[list] = None) -> dict:
    """Run Eisenhower classification. Returns quadrant assignments for all active tasks."""
    conn = _open_conn()
    try:
        tasks = planner.classify_tasks(conn, task_ids)
        return {"tasks": tasks}
    finally:
        conn.close()


@mcp.tool()
def get_config(key: Optional[str] = None) -> dict:
    """Get a config value by key. Omit key to return all config as a flat dict."""
    conn = _open_conn()
    try:
        if key:
            try:
                return {"key": key, "value": core.get_config(conn, key)}
            except KeyError:
                return {"error": f"Unknown config key: {key}"}
        return core.get_all_config(conn)
    finally:
        conn.close()


@mcp.tool()
def set_config(key: str, value: str) -> dict:
    """Set a config value. Returns {ok, key, value}."""
    conn = _open_conn()
    try:
        core.set_config(conn, key, value)
        return {"ok": True, "key": key, "value": value}
    finally:
        conn.close()
