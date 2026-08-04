"""Yazio nutrition sync — angepasst an die reale Feldstruktur.

Yazio nennt die Nährstoffe mit Punkt-Notation und liefert die Tagessumme NICHT
direkt, sondern verteilt auf Mahlzeiten (breakfast / lunch / dinner / snack).
Beispiel-Ausschnitt aus days.json:

    daily_summary:
      goals:              <-- ZIELWERTE, nicht Ist-Werte!
        energy.energy: 2574.8
        nutrient.protein: 145.2
        ...
      meals:
        breakfast:
          nutrients:
            energy.energy: 470.9
            nutrient.protein: 51.99
            nutrient.carb: 35.23
            nutrient.fat: 11.9
        lunch: { nutrients: { ... } }
        dinner: { nutrients: { ... } }
        snack:  { nutrients: { ... } }

Der Parser:
1. Nutzt IMMER die Summe der ``meals[*].nutrients`` (Ist-Werte).
2. Ignoriert ``daily_summary.goals`` (Zielwerte).
3. Faellt auf einen defensiven Aliassen-Scan zurueck, falls Yazio das Layout
   irgendwann aendert — Zielwerte werden dabei explizit ausgeklammert.

Aus der Sandbox kein Netz, daher inline mit dem letzten realen Dump getestet.
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

# Yazio-Feldnamen (Punkt-Notation).
YZ = {
    "kcal":    ["energy.energy", "energy"],
    "protein": ["nutrient.protein", "protein"],
    "carbs":   ["nutrient.carb", "nutrient.carbs", "carb", "carbs"],
    "fat":     ["nutrient.fat", "fat"],
}
GOAL_MARKERS = ("goal", "target", "budget", "limit")
DATE_KEY_HINTS = ("date", "day", "consumed_at")


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


def _pick(d, keys):
    """Erster Treffer per exakter Schluesselgleichheit."""
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d:
            n = _num(d[k])
            if n is not None:
                return n
    return None


def _sum_meals(daily_summary):
    """Summe ueber alle Mahlzeiten in daily_summary.meals."""
    meals = daily_summary.get("meals") if isinstance(daily_summary, dict) else None
    if not isinstance(meals, dict) or not meals:
        return {}
    totals = {"kcal": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    saw = {m: False for m in totals}
    for _, meal in meals.items():
        if not isinstance(meal, dict):
            continue
        nutr = meal.get("nutrients") if isinstance(meal.get("nutrients"), dict) else meal
        for macro, keys in YZ.items():
            v = _pick(nutr, keys)
            if v is not None:
                totals[macro] += v
                saw[macro] = True
    return {m: totals[m] for m in totals if saw[m]}


def _defensive_scan(obj, macro, _depth=0):
    """Rueckfall: irgendwo im Baum den ersten Ist-Wert finden.
    Ziel-Container werden anhand des Elternschluessels ausgeschlossen."""
    if _depth > 6 or obj is None:
        return None
    if isinstance(obj, dict):
        # Direkte Treffer bevorzugen
        v = _pick(obj, YZ[macro])
        if v is not None:
            return v
        for k, val in obj.items():
            kl = str(k).lower()
            if any(g in kl for g in GOAL_MARKERS):
                continue  # Zielwerte ueberspringen
            r = _defensive_scan(val, macro, _depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        acc = 0.0
        saw = False
        for it in obj:
            r = _defensive_scan(it, macro, _depth + 1)
            if r is not None:
                acc += r
                saw = True
        if saw:
            return acc
    return None


def _macros_for_day(day):
    out = {}
    ds = day.get("daily_summary") if isinstance(day, dict) else None

    # 1. Ist-Summe ueber die Mahlzeiten.
    if isinstance(ds, dict):
        out.update(_sum_meals(ds))

    # 2. Defensiver Scan fuer fehlende Makros — Ziel-Container ausgeschlossen.
    for m in YZ:
        if m not in out:
            # 'goals' und 'daily_summary.goals' NICHT betrachten.
            candidate_root = {k: v for k, v in day.items()
                              if isinstance(day, dict) and k not in ("goals",)}
            if isinstance(ds, dict):
                candidate_root["daily_summary"] = {k: v for k, v in ds.items()
                                                   if k not in ("goals",)}
            v = _defensive_scan(candidate_root, m)
            if v is not None:
                out[m] = v

    # 3. Plausibilitaet: Tageswerte unter 20 kcal verwerfen.
    if "kcal" in out and out["kcal"] < 20:
        out.pop("kcal", None)

    return {k: round(v) for k, v in out.items()}


def _find_date(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if any(h in str(k).lower() for h in DATE_KEY_HINTS) and isinstance(v, str):
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
