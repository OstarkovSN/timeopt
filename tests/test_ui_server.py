import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from timeopt import db, core


@pytest.fixture
def ui_env(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = db.get_connection(db_path)
    db.create_schema(conn)
    conn.close()
    with patch.dict(os.environ, {"TIMEOPT_DB": db_path}):
        yield db_path


def test_root_redirects_to_config(ui_env):
    from timeopt.ui_server import app
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/")
    assert resp.status_code in (301, 302, 307, 308)
    assert "/config" in resp.headers["location"]


def test_config_page_returns_html(ui_env):
    from timeopt.ui_server import app
    client = TestClient(app)
    resp = client.get("/config")
    assert resp.status_code == 200
    assert "timeopt" in resp.text
    assert "day_start" in resp.text


def test_config_partial_returns_html(ui_env):
    from timeopt.ui_server import app
    client = TestClient(app)
    resp = client.get("/partials/config")
    assert resp.status_code == 200
    assert "day_start" in resp.text


def test_post_config_saves_value(ui_env):
    from timeopt.ui_server import app
    client = TestClient(app)
    resp = client.post("/api/config/day_start", data={"value": "08:00"})
    assert resp.status_code == 200
    assert "saved" in resp.text.lower()
    # Verify it was actually persisted
    conn = db.get_connection(ui_env)
    assert core.get_config(conn, "day_start") == "08:00"
    conn.close()


def test_post_config_unknown_key_returns_error(ui_env):
    from timeopt.ui_server import app
    client = TestClient(app)
    resp = client.post("/api/config/totally_unknown_key", data={"value": "foo"})
    assert resp.status_code == 200
    assert "error" in resp.text.lower()


def test_get_config_api_returns_all(ui_env):
    from timeopt.ui_server import app
    client = TestClient(app)
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "day_start" in data
    assert data["day_start"] == "09:00"


def test_config_page_db_error_returns_500_with_log(ui_env, caplog):
    """DB failure on config page should be logged."""
    import sqlite3, logging
    from timeopt.ui_server import app
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    client = TestClient(app, raise_server_exceptions=False)
    with patch("timeopt.core.get_all_config", side_effect=sqlite3.OperationalError("disk I/O error")):
        with caplog.at_level(logging.ERROR, logger="timeopt.ui_server"):
            resp = client.get("/config")
    assert resp.status_code == 500
    assert any(r.exc_info is not None for r in caplog.records)


def test_post_config_db_error_returns_error_fragment(ui_env):
    """Non-KeyError DB failure on POST /api/config should return HTMX error fragment, not raw 500."""
    import sqlite3
    from timeopt.ui_server import app
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    client = TestClient(app, raise_server_exceptions=False)
    with patch("timeopt.core.set_config", side_effect=sqlite3.OperationalError("database is locked")):
        resp = client.post("/api/config/day_start", data={"value": "08:00"})
    assert resp.status_code == 200
    assert "error" in resp.text.lower()


def test_get_config_api_db_error_returns_500_with_log(ui_env, caplog):
    """DB failure on GET /api/config should be logged."""
    import sqlite3, logging
    from timeopt.ui_server import app
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    client = TestClient(app, raise_server_exceptions=False)
    with patch("timeopt.core.get_all_config", side_effect=sqlite3.OperationalError("no such table")):
        with caplog.at_level(logging.ERROR, logger="timeopt.ui_server"):
            resp = client.get("/api/config")
    assert resp.status_code == 500
    assert any(r.exc_info is not None for r in caplog.records)


def test_post_config_optional_key_saves_successfully(ui_env):
    """Optional config keys like llm_api_key and caldav_password must be saveable via POST."""
    from timeopt.ui_server import app
    from fastapi.testclient import TestClient
    from timeopt import core, db
    client = TestClient(app)
    for key in ["llm_api_key", "caldav_password", "caldav_username", "llm_model"]:
        resp = client.post(f"/api/config/{key}", data={"value": "test-value"})
        assert resp.status_code == 200, f"POST to {key} returned {resp.status_code}"
        assert "saved" in resp.text.lower(), f"POST to {key} did not show 'saved': {resp.text}"
    conn = db.get_connection(ui_env)
    assert core.get_config(conn, "llm_api_key") == "test-value"
    conn.close()


def test_password_fields_render_as_password_type(ui_env):
    """caldav_password and llm_api_key fields must render as type='password'."""
    from timeopt.ui_server import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/config")
    assert resp.status_code == 200
    assert 'type="password"' in resp.text or "type='password'" in resp.text


def test_post_config_unknown_key_is_logged(ui_env, caplog):
    """POST /api/config/{key} with unknown key logs a warning."""
    import logging
    from timeopt.ui_server import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    with caplog.at_level(logging.WARNING, logger="timeopt.ui_server"):
        response = client.post("/api/config/totally_unknown_key_xyz", data={"value": "foo"})
    assert response.status_code == 200  # HTMX expects 200 to swap
    assert any("totally_unknown_key_xyz" in r.message for r in caplog.records)


def test_get_config_api_does_not_expose_sensitive_values(ui_env):
    """GET /api/config masks llm_api_key and caldav_password."""
    from timeopt.ui_server import app
    from fastapi.testclient import TestClient

    # Set sensitive values first
    client = TestClient(app)
    client.post("/api/config/llm_api_key", data={"value": "sk-super-secret"})
    client.post("/api/config/caldav_password", data={"value": "hunter2"})

    response = client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert body.get("llm_api_key") != "sk-super-secret"
    assert body.get("caldav_password") != "hunter2"
    # Should be masked
    assert body.get("llm_api_key") == "***"
    assert body.get("caldav_password") == "***"
