import sqlite3
import logging
from typing import Any

logger = logging.getLogger(__name__)

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
}


def get_config(conn: sqlite3.Connection, key: str) -> str:
    """Return config value. Raises KeyError for unknown keys."""
    if key not in _CONFIG_DEFAULTS:
        raise KeyError("Unknown config key: %s" % key)
    row = conn.execute(
        "SELECT value FROM config WHERE key = ?", (key,)
    ).fetchone()
    if row:
        return row[0]
    return _CONFIG_DEFAULTS[key]


def set_config(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Persist a config value. Raises KeyError for unknown keys."""
    if key not in _CONFIG_DEFAULTS:
        raise KeyError("Unknown config key: %s" % key)
    conn.execute(
        "INSERT INTO config(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    logger.info("config set: %s = %s", key, value)


def get_all_config(conn: sqlite3.Connection) -> dict[str, str]:
    """Return all config values, merging DB overrides with defaults."""
    cfg = dict(_CONFIG_DEFAULTS)
    for row in conn.execute("SELECT key, value FROM config").fetchall():
        cfg[row[0]] = row[1]
    return cfg
