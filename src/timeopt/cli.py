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
