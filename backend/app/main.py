"""FastAPI backend for Training Cockpit.

Serves:
- /api/kv/{key}         key/value store the frontend uses instead of window.storage
- /api/yazio/sync       trigger a Yazio pull now
- /api/yazio/status     last sync result
- /api/tp/changed-count number of days changed since last TP export
- /api/tp/ics           .ics export (scope=all | changed)
- /                     the built frontend (static)
"""
import os

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from . import db, ics, yazio

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


# ----------------------------- TrainingPeaks ---------------------------------
@app.get("/api/tp/changed-count")
def tp_changed_count():
    return {"count": len(ics.changed())}


@app.get("/api/tp/ics")
def tp_ics(scope: str = "changed"):
    events = ics.compute_events()
    selected = events if scope == "all" else ics.changed(events)
    ics.mark_exported(selected)
    body = ics.build_ics(selected)
    fname = "trainingsplan_alle.ics" if scope == "all" else "trainingsplan_aenderungen.ics"
    return Response(
        content=body,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ------------------------------- Scheduler -----------------------------------
@app.on_event("startup")
def start_scheduler():
    if os.environ.get("YAZIO_SYNC_ENABLED", "true").lower() != "true":
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        return
    hour = int(os.environ.get("YAZIO_SYNC_HOUR", "23"))
    minute = int(os.environ.get("YAZIO_SYNC_MINUTE", "30"))
    tz = os.environ.get("TZ", "Europe/Berlin")
    sched = BackgroundScheduler(timezone=tz)
    sched.add_job(yazio.safe_sync, CronTrigger(hour=hour, minute=minute, timezone=tz))
    sched.start()
    app.state.scheduler = sched


# --------------------------- Static frontend ---------------------------------
# Mounted last so /api/* routes take precedence.
if os.path.isdir(STATIC_DIR):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
