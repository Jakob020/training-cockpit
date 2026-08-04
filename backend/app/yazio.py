"""Yazio nutrition sync.

Yazio has NO official public API. This uses the community tool `yazio-exporter`
(https://pypi.org/project/yazio-exporter/), which logs in with your e-mail and
password against Yazio's private API (yzapi.yazio.com/v15) and dumps your diary.
A server can do this; a browser can't, because Yazio's CORS rules only allow
HTTP/localhost clients.

Honest caveats:
- Unofficial + undocumented. Field names in days.json can change without notice.
  If a sync writes zeros, open /data or the temp dump and adjust MACRO_KEYS below.
- If you enable 2FA on Yazio, the password login will stop working.
- Meals logged via Yazio's AI "Smart Tracking" may be missing from the export.

The parser is deliberately defensive: it walks each day object and picks the
first numeric field whose key matches the macro's regex. Verify once after your
first sync.
"""
import datetime
import json
import os
import re
import subprocess
import tempfile

from . import db

EMAIL = os.environ.get("YAZIO_EMAIL")
PASSWORD = os.environ.get("YAZIO_PASSWORD")

# Regexes used to locate each macro inside a Yazio day record. Adjust if needed.
MACRO_KEYS = {
    "kcal": re.compile(r"(energy|calorie|kcal)", re.I),
    "protein": re.compile(r"protein", re.I),
    "carbs": re.compile(r"(carb)", re.I),
    "fat": re.compile(r"(^|_)fat", re.I),
}
DATE_KEY = re.compile(r"(date|day)", re.I)


def _find_macro(obj, rx):
    """Depth-first search for the first numeric value whose key matches rx."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if rx.search(str(k)) and isinstance(v, (int, float)):
                return v
        for v in obj.values():
            r = _find_macro(v, rx)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_macro(v, rx)
            if r is not None:
                return r
    return None


def _find_date(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if DATE_KEY.search(str(k)) and isinstance(v, str):
                m = re.search(r"\d{4}-\d{2}-\d{2}", v)
                if m:
                    return m.group(0)
    return None


def _iter_days(days_json):
    """days.json may be a list of day objects or a dict keyed by date."""
    if isinstance(days_json, dict):
        for key, day in days_json.items():
            iso = key if re.match(r"\d{4}-\d{2}-\d{2}", str(key)) else _find_date(day)
            if iso:
                yield iso, day
    elif isinstance(days_json, list):
        for day in days_json:
            iso = _find_date(day)
            if iso:
                yield iso, day


def _macros(day):
    out = {}
    for name, rx in MACRO_KEYS.items():
        v = _find_macro(day, rx)
        if v is not None:
            out[name] = round(v)
    return out


def sync():
    """Log into Yazio, pull the diary, merge macros into the `log` blob.
    Returns the number of days updated."""
    if not EMAIL or not PASSWORD:
        raise RuntimeError("YAZIO_EMAIL / YAZIO_PASSWORD sind nicht gesetzt (.env).")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["yazio-exporter", "export-all", EMAIL, PASSWORD, "-o", tmp],
            check=True,
            capture_output=True,
            timeout=180,
        )
        with open(os.path.join(tmp, "days.json"), "r", encoding="utf-8") as f:
            days_json = json.load(f)

    log = db.kv_get("log") or {}
    updated = 0
    for iso, day in _iter_days(days_json):
        macros = _macros(day)
        if not macros:
            continue
        entry = dict(log.get(iso) or {})
        entry.update(macros)  # Yazio overwrites the tracked nutrition values
        log[iso] = entry
        updated += 1
    db.kv_set("log", log)
    db.kv_set(
        "yazio_status",
        {
            "lastSync": datetime.datetime.now().isoformat(timespec="seconds"),
            "updated": updated,
            "ok": True,
        },
    )
    return updated


def safe_sync():
    """Wrapper for the scheduler: never raises, records status."""
    try:
        return sync()
    except Exception as e:  # noqa: BLE001
        db.kv_set(
            "yazio_status",
            {
                "lastSync": datetime.datetime.now().isoformat(timespec="seconds"),
                "ok": False,
                "error": str(e)[:300],
            },
        )
        return 0
