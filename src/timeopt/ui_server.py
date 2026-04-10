import logging
import os
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from timeopt import core, db

logger = logging.getLogger(__name__)

app = FastAPI(title="timeopt")
_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_DEFAULT_DB = str(Path.home() / ".timeopt" / "tasks.db")


def _db_path() -> str:
    return os.environ.get("TIMEOPT_DB", _DEFAULT_DB)


def _open_conn():
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = db.get_connection(path)
    db.create_schema(conn)
    return conn


@app.get("/", response_class=RedirectResponse)
async def root():
    return RedirectResponse(url="/config")


def _mask_sensitive(cfg: dict) -> dict:
    """Return a copy of cfg with sensitive values replaced by '***'."""
    cfg = dict(cfg)
    for k in core._SENSITIVE_CONFIG_KEYS:
        if cfg.get(k):
            cfg[k] = "***"
    return cfg


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    conn = _open_conn()
    try:
        cfg = _mask_sensitive(core.get_all_config(conn))
        return templates.TemplateResponse(
            request, "config.html", {"config": cfg}
        )
    except Exception:
        logger.exception("config_page: failed to render")
        raise
    finally:
        conn.close()


@app.get("/partials/config", response_class=HTMLResponse)
async def config_partial(request: Request):
    conn = _open_conn()
    try:
        cfg = _mask_sensitive(core.get_all_config(conn))
        return templates.TemplateResponse(
            request, "partials/config.html", {"config": cfg}
        )
    except Exception:
        logger.exception("config_partial: failed to render")
        raise
    finally:
        conn.close()


@app.post("/api/config/{key}", response_class=HTMLResponse)
async def set_config_field(request: Request, key: str, value: str = Form("")):
    conn = _open_conn()
    try:
        try:
            if key in core._SENSITIVE_CONFIG_KEYS and value == "***":
                return templates.TemplateResponse(
                    request, "partials/config_field.html",
                    {"key": key, "value": "***", "status": "saved"},
                )
            core.set_config(conn, key, value)
            display_value = "***" if key in core._SENSITIVE_CONFIG_KEYS else value
            return templates.TemplateResponse(
                request, "partials/config_field.html",
                {"key": key, "value": display_value, "status": "saved"},
            )
        except KeyError as e:
            error_msg = e.args[0] if e.args else str(e)
            logger.warning("set_config_field: unknown config key submitted: %s", key)
            return templates.TemplateResponse(
                request, "partials/config_field.html",
                {"key": key, "value": value, "status": "error", "error": error_msg},
            )
        except Exception as e:
            logger.exception("set_config_field: unexpected error for key=%s", key)
            return templates.TemplateResponse(
                request, "partials/config_field.html",
                {"key": key, "value": value, "status": "error",
                 "error": "Internal error — check server logs"},
            )
    finally:
        conn.close()


@app.get("/api/config")
async def get_all_config_api():
    conn = _open_conn()
    try:
        cfg = _mask_sensitive(core.get_all_config(conn))
        return JSONResponse(content=cfg)
    except Exception:
        logger.exception("get_all_config_api: failed")
        raise
    finally:
        conn.close()
