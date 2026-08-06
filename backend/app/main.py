"""FastAPI backend for Training Cockpit.

Serves:
- /api/kv/{key}         key/value store the frontend uses instead of window.storage
- /api/yazio/sync       trigger a Yazio pull now
- /api/yazio/status     last sync result
- /                     the built frontend (static)
"""
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import db, yazio

app = FastAPI(title="Training Cockpit")

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


# ------------------------------- KV store ------------------------------------
@app.get("/api/kv/{key}")
def kv_get(key: str):
    val = db.kv_get(key)
    if val is None:
        raise HTTPException(status_code=404, detail="not found")
    return {"key": key, "value": val}


@app.put("/api/kv/{key}")
async def kv_put(key: str, request: Request):
    body = await request.json()
    db.kv_set(key, body.get("value"))
    return {"ok": True}


@app.delete("/api/kv/{key}")
def kv_delete(key: str):
    db.kv_delete(key)
    return {"ok": True}


# ------------------------------- Yazio ---------------------------------------
@app.post("/api/yazio/sync")
def yazio_sync():
    try:
        updated = yazio.sync()
        return {"ok": True, "updated": updated}
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/api/yazio/status")
def yazio_status():
    return db.kv_get("yazio_status") or {"lastSync": None}


@app.get("/api/yazio/dump/{date}")
def yazio_dump(date: str):
    """Diagnose: liefert die Yazio-Rohdaten fuer einen Tag aus dem letzten
    Sync-Dump. Nur nach einem erfolgreichen Sync verfuegbar."""
    import json as _json, os as _os
    dump = _os.path.join(_os.path.dirname(_os.environ.get("DB_PATH", "/data/cockpit.db")) or "/data", "yazio_last_dump.json")
    if not _os.path.isfile(dump):
        raise HTTPException(status_code=404, detail="Kein Dump vorhanden. Erst 'Jetzt synchronisieren'.")
    with open(dump, "r", encoding="utf-8") as f:
        data = _json.load(f)
    from .yazio import _iter_days, _macros_for_day
    for iso, day in _iter_days(data):
        if iso == date:
            return {"date": iso, "parsed": _macros_for_day(day), "raw": day}
    raise HTTPException(status_code=404, detail=f"Tag {date} nicht in den Yazio-Daten")


# ------------------------------- Scheduler -----------------------------------
@app.on_event("startup")
def start_scheduler():
    if os.environ.get("YAZIO_SYNC_ENABLED", "true").lower() != "true":
        return
    try:
        import datetime
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        return
    minutes = int(os.environ.get("YAZIO_SYNC_INTERVAL_MINUTES", "30"))
    tz = os.environ.get("TZ", "Europe/Berlin")
    sched = BackgroundScheduler(timezone=tz)
    # Erster Lauf gleich beim Start, danach alle YAZIO_SYNC_INTERVAL_MINUTES Minuten.
    sched.add_job(
        yazio.safe_sync,
        IntervalTrigger(minutes=minutes, timezone=tz),
        next_run_time=datetime.datetime.now(),
    )
    sched.start()
    app.state.scheduler = sched


# --------------------------- Static frontend ---------------------------------
# Mounted last so /api/* routes take precedence.
if os.path.isdir(STATIC_DIR):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
