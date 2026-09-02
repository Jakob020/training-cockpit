"""Datenhaltung fuer das Lebensmittel-Tracking.

Bewusst im bestehenden KV-Schema (``db.kv_*``), keine zweite Datenbank und
keine Migration bestehender Keys. Alles hier ist additiv:

    food_log:<YYYY-MM-DD>  Eintraege eines Tages
    food_recent            zuletzt genutzt (MRU, verfaellt nach 10 Tagen)
    food_favorites         manuell angeheftet, unbegrenzt haltbar
    food_custom            selbst angelegte Lebensmittel
    food_recipes           Rezepte

Zwei Entwurfsentscheidungen, die den Rest erklaeren:

1. **per100-Snapshot.** Jeder Log-Eintrag traegt die Naehrwerte, die beim
   Anlegen galten. Aendert jemand das Produkt spaeter bei Open Food Facts
   oder bearbeitet Jakob ein Rezept, bleiben abgeschlossene Tage exakt so,
   wie sie erfasst wurden. Ein Tagesprotokoll, das sich rueckwirkend
   aendert, waere wertlos.

2. **Tagessummen wandern in den ``log``-Key.** Die Tagesansicht liest
   Kalorien und Makros seit jeher aus ``log[<datum>]``; dort schreiben wir
   hin, damit die Anzeige unveraendert bleibt. ``nutrition_source`` markiert
   pro Tag, woher die Werte stammen — ``food_log`` gewinnt immer gegen
   Yazio (siehe yazio.py).
"""
import datetime
import uuid

from . import db

MEALS = ("fruehstueck", "mittag", "abend", "snack")
MACROS = ("kcal", "protein", "carbs", "fat", "sugar", "fiber", "sat_fat", "salt")
# Nur diese vier landen in der Tagesansicht.
DAY_MACROS = ("kcal", "protein", "carbs", "fat")

RECENT_DAYS = 10
RECENT_MAX = 60

LOG_PREFIX = "food_log:"
K_RECENT = "food_recent"
K_FAVORITES = "food_favorites"
K_CUSTOM = "food_custom"
K_RECIPES = "food_recipes"


# ------------------------------- Helfer --------------------------------------
def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _new_id():
    return uuid.uuid4().hex[:12]


def _today():
    return datetime.date.today().isoformat()


def _valid_date(d):
    try:
        datetime.date.fromisoformat(str(d))
        return True
    except (ValueError, TypeError):
        return False


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        n = float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None
    return n if n == n and abs(n) != float("inf") else None


def _clean_per100(raw):
    """Alle acht Naehrwerte, fehlende bleiben None (nie 0 raten)."""
    src = raw if isinstance(raw, dict) else {}
    return {k: _num(src.get(k)) for k in MACROS}


def _meal(v):
    v = str(v or "").strip()
    return v if v in MEALS else "snack"


def _list(key):
    v = db.kv_get(key)
    return v if isinstance(v, list) else []


# ------------------------------ Tageslog -------------------------------------
def _log_key(date):
    return LOG_PREFIX + date


def get_entries(date):
    v = db.kv_get(_log_key(date))
    return v if isinstance(v, list) else []


def _scaled(entry):
    """Naehrwerte eines Eintrags fuer seine tatsaechliche Menge."""
    per100 = _clean_per100(entry.get("per100"))
    grams = _num(entry.get("amount_g")) or 0.0
    factor = grams / 100.0
    return {k: (None if per100[k] is None else per100[k] * factor) for k in MACROS}


def totals_for(entries):
    """Tagessummen. Fehlende Einzelwerte zaehlen als nicht vorhanden und
    werden nicht als 0 verrechnet — ``incomplete`` sagt der Oberflaeche,
    dass mindestens ein Eintrag keine kcal mitbringt."""
    out = {k: 0.0 for k in MACROS}
    incomplete = False
    for e in entries:
        s = _scaled(e)
        if s.get("kcal") is None:
            incomplete = True
        for k in MACROS:
            if s[k] is not None:
                out[k] += s[k]
    res = {k: (round(out[k]) if k == "kcal" else round(out[k], 1)) for k in MACROS}
    res["incomplete"] = incomplete
    return res


def _write_day_totals(date, entries):
    """Tagessummen in den bestehenden ``log``-Key spiegeln — genau die
    Struktur, aus der die Tagesansicht bisher die Yazio-Werte liest.

    Ohne Eintraege werden die Makros und die Quellmarkierung wieder
    entfernt, damit Yazio den Tag erneut befuellen darf.
    """
    log = db.kv_get("log") or {}
    day = dict(log.get(date) or {})
    if entries:
        t = totals_for(entries)
        for k in DAY_MACROS:
            day[k] = t[k]
        day["nutrition_source"] = "food_log"
    else:
        for k in DAY_MACROS:
            day.pop(k, None)
        day.pop("nutrition_source", None)
    if day:
        log[date] = day
    else:
        # Nichts mehr uebrig (weder Gewicht noch Notiz): Datum ganz entfernen,
        # statt einen leeren Eintrag im Log stehen zu lassen.
        log.pop(date, None)
    db.kv_set("log", log)
    return day


def _save_entries(date, entries):
    db.kv_set(_log_key(date), entries)
    return _write_day_totals(date, entries)


def get_day(date):
    entries = get_entries(date)
    log = db.kv_get("log") or {}
    return {
        "date": date,
        "entries": entries,
        "by_meal": {m: [e for e in entries if e.get("meal") == m] for m in MEALS},
        "totals": totals_for(entries),
        "day": log.get(date) or {},
    }


def add_entry(date, payload):
    entry = {
        "id": _new_id(),
        "source": str(payload.get("source") or "off"),
        "ref": str(payload.get("ref") or ""),
        "name": str(payload.get("name") or "").strip() or "Unbenannt",
        "brand": str(payload.get("brand") or "").strip(),
        "meal": _meal(payload.get("meal")),
        "amount_g": _num(payload.get("amount_g")) or 0.0,
        "per100": _clean_per100(payload.get("per100")),
        "created_at": _now(),
    }
    entries = get_entries(date)
    entries.append(entry)
    day = _save_entries(date, entries)
    touch_recent(entry)
    return {"entry": entry, "totals": totals_for(entries), "day": day}


def update_entry(date, entry_id, patch):
    entries = get_entries(date)
    found = None
    for e in entries:
        if e.get("id") == entry_id:
            if "amount_g" in patch:
                e["amount_g"] = _num(patch.get("amount_g")) or 0.0
            if "meal" in patch:
                e["meal"] = _meal(patch.get("meal"))
            found = e
            break
    if found is None:
        return None
    day = _save_entries(date, entries)
    touch_recent(found)
    return {"entry": found, "totals": totals_for(entries), "day": day}


def delete_entry(date, entry_id):
    entries = get_entries(date)
    rest = [e for e in entries if e.get("id") != entry_id]
    if len(rest) == len(entries):
        return None
    day = _save_entries(date, rest)
    return {"ok": True, "totals": totals_for(rest), "day": day}


# ------------------------------- Zuletzt -------------------------------------
def _recent_key(source, ref):
    return f"{source}:{ref}"


def touch_recent(entry):
    """MRU-Liste pflegen. Zweck: eine angebrochene Packung ueber mehrere Tage
    mit einem Tap nachtragen — inklusive der zuletzt genutzten Menge."""
    key = _recent_key(entry.get("source"), entry.get("ref"))
    if not entry.get("ref"):
        return
    items = [i for i in _list(K_RECENT) if i.get("key") != key]
    items.insert(0, {
        "key": key,
        "source": entry.get("source"),
        "ref": entry.get("ref"),
        "name": entry.get("name"),
        "brand": entry.get("brand"),
        "per100": entry.get("per100"),
        "last_amount_g": entry.get("amount_g"),
        "last_used": _now(),
    })
    db.kv_set(K_RECENT, items[:RECENT_MAX])


def get_recent():
    """Nur die letzten RECENT_DAYS Tage. Aeltere fallen raus — dafuer gibt es
    die Favoriten, die nicht verfallen."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=RECENT_DAYS)).isoformat()
    stored = _list(K_RECENT)
    items = [i for i in stored if str(i.get("last_used") or "")[:10] >= cutoff]
    items.sort(key=lambda i: str(i.get("last_used") or ""), reverse=True)
    if len(items) != len(stored):
        db.kv_set(K_RECENT, items)  # Verfallenes gleich mit ausraeumen.
    return items


# ------------------------------ Favoriten ------------------------------------
def get_favorites():
    return _list(K_FAVORITES)


def add_favorite(payload):
    key = _recent_key(payload.get("source") or "off", payload.get("ref") or "")
    items = [i for i in get_favorites() if i.get("key") != key]
    items.insert(0, {
        "key": key,
        "source": payload.get("source") or "off",
        "ref": str(payload.get("ref") or ""),
        "name": str(payload.get("name") or "").strip() or "Unbenannt",
        "brand": str(payload.get("brand") or "").strip(),
        "per100": _clean_per100(payload.get("per100")),
        "last_amount_g": _num(payload.get("amount_g")),
        "added_at": _now(),
    })
    db.kv_set(K_FAVORITES, items)
    return items


def delete_favorite(key):
    items = [i for i in get_favorites() if i.get("key") != key]
    db.kv_set(K_FAVORITES, items)
    return items


# --------------------------- Eigene Lebensmittel -----------------------------
def get_custom():
    return _list(K_CUSTOM)


def add_custom(payload):
    item = {
        "id": _new_id(),
        "name": str(payload.get("name") or "").strip() or "Eigenes Lebensmittel",
        "brand": str(payload.get("brand") or "").strip(),
        "per100": _clean_per100(payload.get("per100")),
        "created_at": _now(),
    }
    items = get_custom()
    items.insert(0, item)
    db.kv_set(K_CUSTOM, items)
    return item


def delete_custom(item_id):
    items = [i for i in get_custom() if i.get("id") != item_id]
    db.kv_set(K_CUSTOM, items)
    return items


# -------------------------------- Rezepte ------------------------------------
def get_recipes():
    return _list(K_RECIPES)


def _ingredient(raw):
    return {
        "source": str(raw.get("source") or "off"),
        "ref": str(raw.get("ref") or ""),
        "name": str(raw.get("name") or "").strip() or "Zutat",
        "amount_g": _num(raw.get("amount_g")) or 0.0,
        "per100": _clean_per100(raw.get("per100")),
    }


def recipe_totals(recipe):
    """Naehrwerte des gesamten Rezepts aus den Zutaten. Wird nie getrennt
    gepflegt, damit Rezept und Zutaten nicht auseinanderlaufen koennen."""
    zutaten = recipe.get("zutaten") or []
    total = {k: 0.0 for k in MACROS}
    for z in zutaten:
        per100 = _clean_per100(z.get("per100"))
        factor = (_num(z.get("amount_g")) or 0.0) / 100.0
        for k in MACROS:
            if per100[k] is not None:
                total[k] += per100[k] * factor
    gramm = sum((_num(z.get("amount_g")) or 0.0) for z in zutaten)
    return total, gramm


def recipe_per_portion(recipe):
    """Gramm und Naehrwerte je Portion — die Basis fuers Buchen."""
    total, gramm = recipe_totals(recipe)
    portionen = _num(recipe.get("portionen")) or 1.0
    if portionen <= 0:
        portionen = 1.0
    return {
        "gramm": gramm / portionen,
        "gesamt_gramm": gramm,
        "portionen": portionen,
        "per_portion": {k: total[k] / portionen for k in MACROS},
        "total": total,
    }


def _recipe_per100(recipe):
    """per100-Snapshot fuers Log: Naehrwerte des Rezepts auf 100 g gerechnet."""
    total, gramm = recipe_totals(recipe)
    if gramm <= 0:
        return {k: None for k in MACROS}
    return {k: total[k] * 100.0 / gramm for k in MACROS}


def save_recipe(payload, recipe_id=None):
    recipes = get_recipes()
    zutaten = [_ingredient(z) for z in (payload.get("zutaten") or [])]
    _, gramm = recipe_totals({"zutaten": zutaten})
    data = {
        "name": str(payload.get("name") or "").strip() or "Rezept",
        "portionen": _num(payload.get("portionen")) or 1.0,
        "gesamt_gramm": gramm,
        "zutaten": zutaten,
        "updated_at": _now(),
    }
    if recipe_id:
        for i, r in enumerate(recipes):
            if r.get("id") == recipe_id:
                recipes[i] = {**r, **data}
                db.kv_set(K_RECIPES, recipes)
                return recipes[i]
        return None
    data["id"] = _new_id()
    data["created_at"] = _now()
    recipes.insert(0, data)
    db.kv_set(K_RECIPES, recipes)
    return data


def delete_recipe(recipe_id):
    recipes = [r for r in get_recipes() if r.get("id") != recipe_id]
    db.kv_set(K_RECIPES, recipes)
    return recipes


def book_recipe(date, recipe_id, portionen, meal):
    """Rezept in den Tag buchen: EIN Eintrag mit source "recipe", nicht
    mehrere Einzelzutaten. Der per100-Snapshot friert das Rezept ein, spaetere
    Bearbeitungen aendern gebuchte Tage deshalb nicht rueckwirkend."""
    recipe = next((r for r in get_recipes() if r.get("id") == recipe_id), None)
    if recipe is None:
        return None
    n = _num(portionen)
    if n is None or n <= 0:
        n = 1.0
    info = recipe_per_portion(recipe)
    return add_entry(date, {
        "source": "recipe",
        "ref": recipe_id,
        "name": recipe.get("name"),
        "brand": f"{n:g} Portion{'en' if n != 1 else ''}".replace(".", ","),
        "meal": meal,
        "amount_g": info["gramm"] * n,
        "per100": _recipe_per100(recipe),
    })
