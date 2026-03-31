import logging
import os
import sys
from datetime import date as _date_type, timedelta
from pathlib import Path
from typing import Optional

import click

from timeopt import core, db, planner
from timeopt.core import TaskInput
from timeopt.llm_client import build_llm_client

logger = logging.getLogger(__name__)

_DEFAULT_DB = str(Path.home() / ".timeopt" / "tasks.db")


def _db_path() -> str:
    return os.environ.get("TIMEOPT_DB", _DEFAULT_DB)


def _open_conn():
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = db.get_connection(path)
    db.create_schema(conn)
    return conn


def _get_llm_client(conn):
    config = core.get_all_config(conn)
    try:
        return build_llm_client(config)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _get_caldav_client(conn):
    from timeopt.caldav_client import CalDAVClient
    url = core.get_config(conn, "caldav_url") or "https://caldav.yandex.ru"
    username = core.get_config(conn, "caldav_username")
    password = core.get_config(conn, "caldav_password")
    read_cals = core.get_config(conn, "caldav_read_calendars") or "all"
    tasks_cal = core.get_config(conn, "caldav_tasks_calendar") or "Timeopt"
    if not username or not password:
        return None
    return CalDAVClient(url=url, username=username, password=password,
                        read_calendars=read_cals, tasks_calendar=tasks_cal)


def _format_tags(task: dict) -> str:
    tags = []
    if task.get("category"):
        tags.append(task["category"])
    if task.get("priority"):
        tags.append(task["priority"])
    if task.get("urgent"):
        tags.append("urgent")
    if task.get("due_at"):
        tags.append(f"due {task['due_at'][:10]}")
    return f"[{', '.join(tags)}]" if tags else ""


def _print_task_line(task: dict, show_notes: bool = False):
    did = task.get("display_id", "")
    tags = _format_tags(task)
    notes_suffix = ""
    if show_notes and task.get("notes"):
        last_note = task["notes"].strip().split("\n")[-1]
        notes_suffix = f" — {last_note[:60]}"
    click.echo(f"  {did:<35} {tags}{notes_suffix}")


def _print_tasks(tasks: list):
    """Print a list of task dicts grouped by status."""
    pending = [t for t in tasks if t["status"] == "pending"]
    delegated = [t for t in tasks if t["status"] == "delegated"]

    if not pending and not delegated:
        click.echo("No tasks.")
        return

    if pending:
        click.echo(f"Pending ({len(pending)})")
        for t in pending:
            _print_task_line(t)

    if delegated:
        if pending:
            click.echo("")
        click.echo(f"Being handled by Claude ({len(delegated)})")
        for t in delegated:
            _print_task_line(t, show_notes=True)


@click.group()
def cli():
    """Timeopt — personal task manager with calendar integration."""
    pass


@cli.command()
@click.option("--status", default=None, help="Filter: pending, delegated, done")
@click.option("--priority", default=None, help="Filter: high, medium, low")
@click.option("--category", default=None, help="Filter by category")
@click.option("--all", "include_old_done", is_flag=True, default=False,
              help="Include done tasks older than hide_done_after_days")
def tasks(status, priority, category, include_old_done):
    """List tasks."""
    conn = _open_conn()
    try:
        # core.list_tasks returns a bare list (not a dict)
        tasks_list = core.list_tasks(conn, status=status, priority=priority,
                                     category=category, include_old_done=include_old_done)
        _print_tasks(tasks_list)
    finally:
        conn.close()


@cli.command()
@click.option("--today", "period", flag_value="today",
              help="Only today's completed tasks")
@click.option("--week", "period", flag_value="week",
              help="Tasks completed in the last 7 days")
@click.option("--all", "period", flag_value="all", default=True,
              help="All completed tasks")
def history(period):
    """View completed tasks."""
    conn = _open_conn()
    try:
        # core.list_tasks returns a bare list
        done_tasks = core.list_tasks(conn, status="done", include_old_done=True)

        if period == "today":
            today = _date_type.today().isoformat()
            done_tasks = [t for t in done_tasks if (t.get("done_at") or "").startswith(today)]
        elif period == "week":
            cutoff = (_date_type.today() - timedelta(days=7)).isoformat()
            done_tasks = [t for t in done_tasks if (t.get("done_at") or "") >= cutoff]

        if not done_tasks:
            click.echo("No completed tasks in this period.")
            return

        click.echo(f"Completed ({len(done_tasks)})")
        for t in done_tasks:
            done_at = (t.get("done_at") or "")[:10]
            click.echo(f"  {t.get('display_id', ''):<35} {done_at}  {t.get('title', '')}")
    finally:
        conn.close()


@cli.group()
def config():
    """Manage configuration."""
    pass


@config.command("get")
@click.argument("key", required=False)
def config_get(key):
    """Get one or all config values."""
    conn = _open_conn()
    try:
        if key:
            value = core.get_config(conn, key)
            click.echo(f"{key} = {value if value is not None else '(not set)'}")
        else:
            all_cfg = core.get_all_config(conn)
            for k, v in sorted(all_cfg.items()):
                click.echo(f"{k} = {v if v is not None else '(not set)'}")
    finally:
        conn.close()


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a config value."""
    conn = _open_conn()
    try:
        core.set_config(conn, key, value)
        click.echo(f"Set {key} = {value}")
    finally:
        conn.close()


@cli.command()
@click.argument("queries", nargs=-1, required=True)
def done(queries):
    """Mark tasks as done by fuzzy match. Accepts partial names."""
    conn = _open_conn()
    try:
        min_score = int(core.get_config(conn, "fuzzy_match_min_score") or 80)
        ask_gap = int(core.get_config(conn, "fuzzy_match_ask_gap") or 10)

        task_ids = []
        confirmed_dids = []

        for query in queries:
            candidates = core.fuzzy_match_tasks(conn, query)

            if not candidates or candidates[0]["score"] < min_score:
                click.echo(f"No confident match for '{query}'.")
                if candidates:
                    click.echo("  Closest:")
                    for c in candidates[:3]:
                        click.echo(f"    {c['display_id']} (score: {c['score']:.0f})")
                continue

            top = candidates[0]
            second_score = candidates[1]["score"] if len(candidates) > 1 else 0

            if len(candidates) >= 2 and (top["score"] - second_score) < ask_gap:
                click.echo(f"Ambiguous match for '{query}':")
                for i, c in enumerate(candidates[:3], 1):
                    click.echo(f"  {i}. {c['display_id']} — {c['title']} (score: {c['score']:.0f})")
                choice = click.prompt("Pick number (0 to skip)", type=int, default=0)
                if choice == 0:
                    continue
                if 1 <= choice <= min(3, len(candidates)):
                    task_ids.append(candidates[choice - 1]["task_id"])
                    confirmed_dids.append(candidates[choice - 1]["display_id"])
            else:
                task_ids.append(top["task_id"])
                confirmed_dids.append(top["display_id"])

        if task_ids:
            core.mark_done(conn, task_ids)
            click.echo("Done:")
            for did in confirmed_dids:
                click.echo(f"  ✓ {did}")
    finally:
        conn.close()


@cli.command()
@click.argument("text")
def dump(text):
    """Brain-dump tasks in free-form text. Parses with LLM and saves."""
    conn = _open_conn()
    try:
        llm = _get_llm_client(conn)
        result = core.cli_dump(conn, llm, text)
        click.echo(f"Added {result['count']} task(s):")
        for did in result["display_ids"]:
            click.echo(f"  {did}")
    finally:
        conn.close()


@cli.command()
@click.option("--date", "plan_date", default=None,
              help="Date to plan for (YYYY-MM-DD, default today)")
def plan(plan_date):
    """Generate and push a daily task schedule."""
    conn = _open_conn()
    try:
        caldav = _get_caldav_client(conn)
        if not caldav:
            click.echo("Warning: CalDAV not configured — planning without calendar data.", err=True)

        target = plan_date or _date_type.today().isoformat()
        events = []
        if caldav:
            try:
                raw_events = caldav.get_events(target, days=1)
                events = [{"start": e.start, "end": e.end, "title": e.title} for e in raw_events]
            except Exception:
                logger.exception("plan: CalDAV unavailable, proceeding without calendar")

        proposal = planner.get_plan_proposal(conn, events, target)
        blocks = proposal.get("blocks", [])

        if not blocks:
            click.echo("No tasks to schedule.")
            return

        click.echo("Proposed schedule:")
        from datetime import datetime as _dt, timedelta as _td
        for b in blocks:
            start_str = b.get("start", "")
            if len(start_str) >= 16:
                start_dt = _dt.fromisoformat(start_str)
                end_dt = start_dt + _td(minutes=b.get("duration_min", 0))
                click.echo(
                    f"  {start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"
                    f"  {b.get('display_id', ''):<35} [{b.get('quadrant', '')}]"
                )

        deferred = proposal.get("deferred", [])
        if deferred:
            click.echo(f"\nDeferred ({len(deferred)}):")
            for d in deferred:
                click.echo(f"  {d.get('display_id', '')} — {d.get('title', '')}")

        if not caldav:
            click.echo("\nCalDAV not configured — skipping calendar push.")
            return

        if not click.confirm("\nPush to calendar?", default=True):
            return

        planner.push_calendar_blocks(conn, proposal, target, caldav)
        click.echo(f"Pushed {len(blocks)} block(s) to calendar.")
    finally:
        conn.close()


@cli.command("check-urgent")
def check_urgent():
    """Classify tasks and show Q3 (urgent, not important) tasks for delegation."""
    conn = _open_conn()
    try:
        result = planner.classify_tasks(conn)
        q3_tasks = [t for t in result if t.get("quadrant") == "Q3"]

        if not q3_tasks:
            click.echo("No Q3 tasks. All clear.")
            return

        click.echo(f"Q3 tasks (urgent + not important) — {len(q3_tasks)} found:")
        for t in q3_tasks:
            click.echo(f"  {t.get('display_id', ''):<35} {t.get('title', '')}")
        click.echo("\nTip: Run '/check-urgent' in Claude Code to automatically delegate these.")
    finally:
        conn.close()


@cli.command()
def sync():
    """Sync due dates for tasks bound to calendar events."""
    conn = _open_conn()
    try:
        caldav = _get_caldav_client(conn)
        if not caldav:
            click.echo("CalDAV not configured. Set caldav_username and caldav_password.")
            return

        try:
            events_raw = caldav.get_events(_date_type.today().isoformat(), days=90)
            events = [{"start": e.start, "end": e.end, "title": e.title} for e in events_raw]
        except Exception as e:
            click.echo(f"CalDAV error: {e}", err=True)
            return

        changes = core.sync_bound_tasks(conn, events)
        resolved = core.try_resolve_unresolved(conn, events)
        still_unresolved = core.get_unresolved_tasks(conn)

        if changes:
            click.echo(f"Updated {len(changes)} task due date(s):")
            for c in changes:
                if c["status"] == "updated":
                    old = (c["old_due_at"] or "")[:10]
                    new = (c["new_due_at"] or "")[:10]
                    click.echo(f"  {c['display_id']}  {old} → {new}")
                elif c["status"] == "event_missing":
                    click.echo(f"  {c['display_id']}  ⚠ bound event deleted — due date preserved")
        else:
            click.echo("No due date changes.")

        newly_resolved = [r for r in resolved if r["status"] == "resolved"]
        if newly_resolved:
            click.echo(f"\nResolved {len(newly_resolved)} previously unresolved task(s).")

        if still_unresolved:
            click.echo(f"\n{len(still_unresolved)} task(s) still have unresolved calendar references:")
            for t in still_unresolved:
                click.echo(f"  {t['display_id']}  ref: {t.get('due_event_label', '?')}")
            click.echo("Run '/sync' in Claude Code to resolve these interactively.")
    finally:
        conn.close()
