from timeopt.core import get_config, set_config, get_all_config

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
}


def test_get_config_returns_default(conn):
    assert get_config(conn, "day_start") == "09:00"


def test_get_config_returns_override(conn):
    set_config(conn, "day_start", "08:00")
    assert get_config(conn, "day_start") == "08:00"


def test_get_config_unknown_key_raises(conn):
    import pytest
    with pytest.raises(KeyError):
        get_config(conn, "nonexistent_key")


def test_get_all_config_returns_merged(conn):
    set_config(conn, "day_start", "08:00")
    cfg = get_all_config(conn)
    assert cfg["day_start"] == "08:00"
    assert cfg["day_end"] == "18:00"  # default still present


def test_set_config_persists(conn):
    set_config(conn, "default_effort", "large")
    assert get_config(conn, "default_effort") == "large"
