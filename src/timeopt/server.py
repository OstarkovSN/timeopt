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
        try:
            core.set_config(conn, key, value)
            display_value = "***" if key in core._SENSITIVE_CONFIG_KEYS else value
            return {"ok": True, "key": key, "value": display_value}
        except KeyError as e:
            logger.warning("set_config: rejected unknown key=%s", key)
            return {"ok": False, "error": str(e)}
    finally:
        conn.close()


@mcp.tool()
def get_dump_templates(fragments: list) -> dict:
    """
    Build sparse task templates from raw text fragments for Claude to fill.
    Fetches CalDAV events for calendar reference detection (next 30 days).
    Returns {schema: {...}, templates: [{raw, title, priority: "?", ...}]}.
    """
    conn = _open_conn()
    try:
        caldav = _get_caldav(conn)
        events = []
        if caldav:
            # get_events never raises — degrades to [] internally on CalDAV failure
            events = caldav.get_events(_date_type.today().isoformat(), days=30)
        return core.get_dump_templates(fragments, events)
    finally:
        conn.close()


@mcp.tool()
def dump_tasks(tasks: list) -> dict:
    """
    Save a batch of filled task objects. Returns {count, display_ids}.
    tasks should be completed templates from get_dump_templates.
    """
    conn = _open_conn()
    try:
        task_inputs = [_dict_to_task_input(t) for t in tasks]
        display_ids = core.dump_tasks(conn, task_inputs)
        return {"count": len(display_ids), "display_ids": display_ids}
    finally:
        conn.close()


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
        try:
            min_score = int(core.get_config(conn, "calendar_fuzzy_min_score"))
        except ValueError:
            logger.warning(
                "resolve_calendar_reference: calendar_fuzzy_min_score is not an integer, using default 50"
            )
            min_score = 50
        match = core.resolve_calendar_reference(label, events_raw, min_score=min_score)
        return {"candidates": [match] if match else []}
    finally:
        conn.close()


@mcp.tool()
def get_calendar_events(date: Optional[str] = None, days: int = 1) -> dict:
    """
    Fetch events from all configured read calendars. Read-only.
    Returns {events: [{title, start, end, uid}]}. Defaults to today.
    """
    conn = _open_conn()
    try:
        caldav = _get_caldav(conn)
        if not caldav:
            return {"events": [], "warning": "CalDAV not configured"}
        target = _parse_date(date).isoformat()
        events = caldav.get_events(target, days=days)
        return {"events": [
            {"title": e.title, "start": e.start, "end": e.end, "uid": e.uid}
            for e in events
        ]}
    finally:
        conn.close()


@mcp.tool()
def get_plan_proposal(date: Optional[str] = None) -> dict:
    """
    Server-side scheduling for the given date (default today).
    Fetches calendar events for free/busy; warns but proceeds if CalDAV unavailable.
    Returns {blocks: [{task_id, display_id, title, start, duration_min, quadrant}],
             deferred: [...]}.
    """
    conn = _open_conn()
    try:
        caldav = _get_caldav(conn)
        target = _parse_date(date).isoformat()
        events = []
        if caldav:
            # get_events never raises — degrades to [] internally on CalDAV failure
            events_raw = caldav.get_events(target, days=1)
            events = [{"start": e.start, "end": e.end, "title": e.title} for e in events_raw]
        return planner.get_plan_proposal(conn, events, target)
    finally:
        conn.close()


@mcp.tool()
def push_calendar_blocks(blocks: list, date: Optional[str] = None) -> dict:
    """
    Transactional push: all CalDAV writes collected first, SQLite committed only on success.
    blocks: list of {task_id, display_id, title, start, duration_min, quadrant}.
    Returns {ok: bool, pushed: int}.
    """
    conn = _open_conn()
    try:
        caldav = _get_caldav(conn)
        if not caldav:
            return {"ok": False, "error": "CalDAV not configured"}
        target = _parse_date(date).isoformat()
        try:
            planner.push_calendar_blocks(conn, {"blocks": blocks}, target, caldav)
        except Exception as e:
            logger.exception("push_calendar_blocks: failed")
            return {"ok": False, "error": str(e)}
        return {"ok": True, "pushed": len(blocks)}
    finally:
        conn.close()


@mcp.tool()
def sync_calendar(date_range_days: int = 30) -> dict:
    """
    Sync calendar event bindings:
    1. Updates due_at for tasks bound to moved events (algorithmic).
    2. Attempts to resolve tasks with unresolved calendar references.
    Returns {ok, updated: [...], resolved: [...], unresolved_remaining: [...]}.
    """
    conn = _open_conn()
    try:
        caldav = _get_caldav(conn)
        if not caldav:
            return {"ok": False, "error": "CalDAV not configured"}
        # get_events never raises — degrades to [] internally on failure
        events_raw = caldav.get_events(_date_type.today().isoformat(), days=date_range_days)
        updated = core.sync_bound_tasks(conn, events_raw)
        resolved = core.try_resolve_unresolved(conn, events_raw)
        still_unresolved = core.get_unresolved_tasks(conn)
        return {
            "ok": True,
            "updated": updated,
            "resolved": resolved,
            "unresolved_remaining": still_unresolved,
        }
    finally:
        conn.close()


def main():
    mcp.run(transport="stdio")
