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
