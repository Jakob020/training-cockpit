"""Yazio nutrition sync — praezise Feldzuordnung.

Yazio hat KEINE offizielle API. Der Sync nutzt das Community-Tool
``yazio-exporter``, das sich mit E-Mail/Passwort gegen Yazios private API
einloggt. Ein Server kann das; ein Browser scheitert an CORS.

Warum diese Datei ueberarbeitet ist
-----------------------------------
Die erste Version hat pro Tag "das erste passende numerische Feld" genommen.
Das kann ein Zielwert oder der Energiegehalt eines einzelnen Produkts sein,
nicht die Tagessumme. Deshalb kamen Werte wie kcal 193 fuer den ganzen Tag
heraus.

Der Parser hier arbeitet in drei Stufen und nimmt das erste plausible Ergebnis:

1. **Direkte Tagesfelder** wie ``consumed_energy``, ``consumed_nutrients`` in
   mehreren Auspraegungen.
2. **Summe ueber die Items** eines Tages, wenn ``items`` / ``foods`` /
   ``entries`` vorhanden sind — jedes Item liefert Energie und Naehrstoffe,
   die aufsummiert werden.
3. **Zielwerte** (``*_goal``) sind nur ein allerletzter Rueckfall.

Bei jedem Lauf wird die zuletzt gezogene ``days.json`` nach
``<DB_DIR>/yazio_last_dump.json`` geschrieben, damit man die Feldnamen bei
Bedarf abgleichen kann.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile

from . import db

EMAIL = os.environ.get("YAZIO_EMAIL")
PASSWORD = os.environ.get("YAZIO_PASSWORD")

DATA_DIR = os.path.dirname(os.environ.get("DB_PATH", "/data/cockpit.db")) or "/data"
DUMP_PATH = os.path.join(DATA_DIR, "yazio_last_dump.json")

NUTRIENT_TOTAL_KEYS = [
    "consumed_nutrients", "nutrients_consumed", "totals",
    "consumed", "nutrients",
]

MACRO_ALIASES = {
    "kcal": [
        "consumed_energy", "energy_consumed", "energy", "kcal",
        "consumed_kcal", "total_energy", "sum_energy",
    ],
    "protein": [
        "consumed_protein", "protein_consumed", "protein",
        "nutrient_protein", "total_protein",
    ],
    "carbs": [
        "consumed_carb", "carb_consumed", "carb", "carbs",
        "carbohydrates", "nutrient_carb", "total_carb",
    ],
    "fat": [
        "consumed_fat", "fat_consumed", "fat",
        "nutrient_fat", "total_fat",
    ],
}
ITEM_LIST_KEYS = ["items", "foods", "entries", "products", "consumed_items"]
DATE_KEY_HINTS = ("date", "day", "consumed_at")


def _norm(k):
    return re.sub(r"[^a-z0-9]+", "_", str(k).lower()).strip("_")


def _is_goal(k):
    n = _norm(k)
    return "goal" in n or "target" in n or "budget" in n or "limit" in n


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "."))
        except ValueError:
            return None
    return None


def _find_key(obj, aliases, skip_goals=True):
    if not isinstance(obj, dict):
        return None
    norm_aliases = [_norm(a) for a in aliases]
    for k, v in obj.items():
        if skip_goals and _is_goal(k):
            continue
        if _norm(k) in norm_aliases:
            n = _num(v)
            if n is not None:
                return n
    return None


def _macro_from_dict(d, macro):
    return _find_key(d, MACRO_ALIASES[macro], skip_goals=True)


def _sum_items(day):
    lists = []
    if isinstance(day, dict):
        for k in ITEM_LIST_KEYS:
            if k in day and isinstance(day[k], list):
                lists.append(day[k])
    if not lists:
        return {}
    totals = {"kcal": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    saw = {m: False for m in totals}
    for lst in lists:
        for item in lst:
            if not isinstance(item, dict):
                continue
            sub = None
            for k in NUTRIENT_TOTAL_KEYS:
                if isinstance(item.get(k), dict):
                    sub = item[k]
                    break
            for m in totals:
                v = _macro_from_dict(sub or {}, m)
                if v is None:
                    v = _macro_from_dict(item, m)
                if v is not None:
                    totals[m] += v
                    saw[m] = True
    return {m: totals[m] for m in totals if saw[m]}


def _fallback_goal(day, macro):
    if not isinstance(day, dict):
        return None
    for k, v in day.items():
        nk = _norm(k)
        if "goal" in nk and macro in nk:
            return _num(v)
    return None


def _macros_for_day(day):
    out = {}
    for m in MACRO_ALIASES:
        v = _macro_from_dict(day, m)
        if v is None:
            for tk in NUTRIENT_TOTAL_KEYS:
                sub = day.get(tk) if isinstance(day, dict) else None
                if isinstance(sub, dict):
                    v = _macro_from_dict(sub, m)
                    if v is not None:
                        break
        if v is not None:
            out[m] = v

    if len(out) < 4:
        for m, v in _sum_items(day).items():
            out.setdefault(m, v)

    for m in list(MACRO_ALIASES.keys()):
        if m not in out:
            v = _fallback_goal(day, m)
            if v is not None:
                out[m] = v

    if "kcal" in out and out["kcal"] < 50:
        out.pop("kcal", None)

    return {k: round(v) for k, v in out.items()}


def _find_date(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            nk = _norm(k)
            if any(h in nk for h in DATE_KEY_HINTS) and isinstance(v, str):
                m = re.search(r"\d{4}-\d{2}-\d{2}", v)
                if m:
                    return m.group(0)
    return None


def _iter_days(days_json):
    if isinstance(days_json, dict) and "days" in days_json and isinstance(days_json["days"], (list, dict)):
        days_json = days_json["days"]
    if isinstance(days_json, dict):
        for key, day in days_json.items():
            iso = key if re.match(r"^\d{4}-\d{2}-\d{2}$", str(key)) else _find_date(day)
            if iso:
                yield iso, day
    elif isinstance(days_json, list):
        for day in days_json:
            iso = _find_date(day)
            if iso:
                yield iso, day


def _run_exporter(tmp):
    binary = shutil.which("yazio-exporter") or "yazio-exporter"
    subprocess.run(
        [binary, "export-all", EMAIL, PASSWORD, "-o", tmp],
        check=True, capture_output=True, timeout=180,
    )
    path = os.path.join(tmp, "days.json")
    if not os.path.isfile(path):
        raise RuntimeError("days.json wurde nicht erzeugt")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _dump_for_debug(days_json):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(DUMP_PATH, "w", encoding="utf-8") as f:
            json.dump(days_json, f, ensure_ascii=False)
    except Exception:
        pass


def sync():
    if not EMAIL or not PASSWORD:
        raise RuntimeError("YAZIO_EMAIL / YAZIO_PASSWORD sind nicht gesetzt (.env).")
    with tempfile.TemporaryDirectory() as tmp:
        days_json = _run_exporter(tmp)
    _dump_for_debug(days_json)

    log = db.kv_get("log") or {}
    updated = 0
    for iso, day in _iter_days(days_json):
        macros = _macros_for_day(day)
        if not macros:
            continue
        entry = dict(log.get(iso) or {})
        entry.update(macros)
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
    try:
        return sync()
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", "ignore")[:300] or str(e)[:300]
        db.kv_set("yazio_status", {
            "lastSync": datetime.datetime.now().isoformat(timespec="seconds"),
            "ok": False, "error": f"exporter: {err}",
        })
        return 0
    except Exception as e:
        db.kv_set("yazio_status", {
            "lastSync": datetime.datetime.now().isoformat(timespec="seconds"),
            "ok": False, "error": str(e)[:300],
        })
        return 0
