"""Open Food Facts (OFF) client — die einzige externe Datenquelle fuer das
Lebensmittel-Tracking.

Zwei Wege in die Datenbank:

1. Volltextsuche ueber den Such-Index ``search.openfoodfacts.org/search``.
   Die Parameter sind gegen die OpenAPI-Spec geprueft (Stand 2026-09):
   ``q``, ``langs``, ``page_size``, ``page``, ``fields``, ``sort_by``,
   ``facets``, ``charts``, ``index_id``. Ein ``countries``-Parameter
   existiert NICHT, und die Lucene-Variante ``countries_tags:germany``
   liefert auf diesem Index 0 Treffer. Die Gewichtung auf deutsche Produkte
   passiert deshalb hier im Client (siehe ``_rank_key``) — das hat den
   Nebeneffekt, dass der CGI-Fallback exakt dieselbe Sortierung bekommt.

2. Fallback ``world.openfoodfacts.org/cgi/search.pl``, falls der Index
   streikt. Achtung: der Fallback ist selbst unzuverlaessig — in Messungen
   kamen auf drei Anfragen zwei 200er und eine 503. Beide Wege muessen
   deshalb sauber ins leere Ergebnis laufen statt zu werfen.

Barcode-Lookups gehen ueber ``lookup_barcode`` gegen die v2-Produkt-API.
Die Funktion ist bewusst frei von UI- und Suchlogik: Phase 2 (Kamera-
Scanner) haengt nur die Kamera davor und ruft sie unveraendert auf.

Datenqualitaet: fehlende Naehrwerte werden zu ``None``, niemals zu 0. Ein
geratener Nullwert waere im Tagesprotokoll schlimmer als eine Luecke.
"""
import time

import requests

from . import db

# --------------------------------------------------------------------------
# Open Food Facts verlangt einen aussagekraeftigen User-Agent mit Kontakt bei
# JEDEM Request; ohne den drohen Rate-Limits oder Sperren. Die Adresse geht
# damit bei jeder Suche und jedem Barcode-Lookup an OFF und steht in deren
# Server-Logs — beim Wechsel auf eine Alias-Adresse einfach hier ersetzen.
CONTACT_EMAIL = "jakobbue@icloud.com"
USER_AGENT = f"TrainingCockpit/1.0 ({CONTACT_EMAIL})"

SEARCH_URL = "https://search.openfoodfacts.org/search"
CGI_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"

TIMEOUT = 8
MAX_RESULTS = 20

# Angeforderte Felder. ``lang`` und ``countries_tags`` stehen nicht auf der
# Nutzliste, werden aber fuer die Deutschland-Gewichtung gebraucht — ohne sie
# gaebe es kein Signal, nach dem sich sortieren liesse.
FIELDS = [
    "code", "product_name", "product_name_de", "brands", "quantity",
    "serving_size", "serving_quantity", "nutriments", "lang", "countries_tags",
]

# Interner Name -> OFF-Feldname (jeweils pro 100 g).
NUTRIENTS = {
    "kcal": "energy-kcal_100g",
    "protein": "proteins_100g",
    "carbs": "carbohydrates_100g",
    "fat": "fat_100g",
    # Die folgenden vier werden gespeichert, aber bewusst nicht angezeigt.
    "sugar": "sugars_100g",
    "fiber": "fiber_100g",
    "sat_fat": "saturated-fat_100g",
    "salt": "salt_100g",
}

CACHE_PREFIX = "food_cache:barcode:"
CACHE_TTL = 30 * 24 * 3600  # 30 Tage


def _headers():
    return {"User-Agent": USER_AGENT, "Accept": "application/json"}


def _num(v):
    """Zahl oder None. Leerstrings und Unsinn werden None, nicht 0."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", ".")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _brand(v):
    """``brands`` kommt im Such-Index als Liste, im Barcode-Endpunkt als
    String. Beides auf einen kurzen String normalisieren.

    OFF-Markenlisten enthalten reichlich Dubletten und Schreibvarianten
    ("Gut & Guenstig, Gut&Guenstig, Gut & Guenstig, ..."). Ungefiltert
    frisst das in der Trefferliste drei Zeilen, ohne etwas auszusagen —
    deshalb doppelte Eintraege raus und auf zwei Marken kappen.
    """
    parts = v if isinstance(v, list) else str(v or "").split(",")
    out, seen = [], set()
    for raw in parts:
        name = str(raw or "").strip()
        if not name:
            continue
        norm = "".join(ch for ch in name.lower() if ch.isalnum())
        if norm in seen:
            continue
        seen.add(norm)
        out.append(name)
    return ", ".join(out[:2])


def _name(p):
    """``product_name`` ist haeufig leer, waehrend ``product_name_de``
    gefuellt ist — deutsche Variante bevorzugen."""
    for key in ("product_name_de", "product_name", "generic_name_de", "generic_name"):
        v = p.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _per100(nutriments):
    """Alle acht Naehrwerte pro 100 g; fehlende bleiben None."""
    n = nutriments if isinstance(nutriments, dict) else {}
    return {key: _num(n.get(off_key)) for key, off_key in NUTRIENTS.items()}


def _normalize(p):
    """Ein OFF-Produkt in die Form bringen, die App und Log verwenden."""
    if not isinstance(p, dict):
        return None
    code = str(p.get("code") or "").strip()
    per100 = _per100(p.get("nutriments"))
    name = _name(p)
    if not code and not name:
        return None
    return {
        "code": code,
        "name": name or "Unbenanntes Produkt",
        "brand": _brand(p.get("brands")),
        "quantity": (p.get("quantity") or "").strip() if isinstance(p.get("quantity"), str) else "",
        "serving_size": (p.get("serving_size") or "").strip() if isinstance(p.get("serving_size"), str) else "",
        "serving_quantity": _num(p.get("serving_quantity")),
        "per100": per100,
        # Nur fuer die Sortierung, nicht fuer die Anzeige.
        "_lang": p.get("lang"),
        "_countries": p.get("countries_tags") or [],
    }


def _rank_key(item, index):
    """Sortierschluessel: erst Brauchbarkeit, dann Herkunft, dann Original-
    reihenfolge (stabil).

    1. Treffer ohne kcal ans Ende — mit ``langs=de`` liefert OFF deutlich
       mehr Produkte, aber viele davon ohne Naehrwerte (gemessen: 79 Treffer
       alle mit kcal ohne ``langs``, 381 mit vielen Luecken mit ``langs=de``).
       Ohne diese Regel waere die Suche unbrauchbar.
    2. Deutsche Produkte bevorzugen.
    """
    has_kcal = 0 if item["per100"].get("kcal") is not None else 1
    countries = item.get("_countries") or []
    german = 0 if (
        item.get("_lang") == "de"
        or any("germany" in str(c).lower() for c in countries)
        or any("deutschland" in str(c).lower() for c in countries)
    ) else 1
    return (has_kcal, german, index)


def _finish(items):
    """Sortieren, kappen und die internen Sortierfelder entfernen.

    Der Index dient als letztes Sortierkriterium und haelt damit die
    Relevanzreihenfolge von OFF innerhalb gleicher Rangstufen stabil.
    """
    pairs = list(enumerate(it for it in items if it))
    ranked = sorted(pairs, key=lambda pair: _rank_key(pair[1], pair[0]))
    out = []
    for _, it in ranked[:MAX_RESULTS]:
        it.pop("_lang", None)
        it.pop("_countries", None)
        out.append(it)
    return out


def _search_index(q, page_size):
    r = requests.get(
        SEARCH_URL,
        params={
            "q": q,
            "page_size": page_size,
            "fields": ",".join(FIELDS),
            "langs": "de",
        },
        headers=_headers(),
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    return [_normalize(h) for h in (data.get("hits") or [])]


def _search_cgi(q, page_size):
    r = requests.get(
        CGI_SEARCH_URL,
        params={
            "search_terms": q,
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "page_size": page_size,
        },
        headers=_headers(),
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    return [_normalize(p) for p in (data.get("products") or [])]


def search(q, page_size=MAX_RESULTS):
    """Volltextsuche. Gibt immer ein Dict zurueck, wirft nie.

    ``offline`` sagt der Oberflaeche, dass keine Quelle erreichbar war —
    dann zeigt das Overlay den Offline-Hinweis statt eines Fehlers.
    """
    q = (q or "").strip()
    if not q:
        return {"items": [], "offline": False, "source": None}

    page_size = max(1, min(int(page_size or MAX_RESULTS), MAX_RESULTS))

    try:
        return {"items": _finish(_search_index(q, page_size)),
                "offline": False, "source": "index"}
    except Exception:
        pass  # Index streikt -> Fallback versuchen.

    try:
        return {"items": _finish(_search_cgi(q, page_size)),
                "offline": False, "source": "cgi"}
    except Exception:
        # Beide Wege tot: kein Netz oder OFF down. Leeres Ergebnis mit Flag,
        # damit die App auf "Zuletzt" bleiben kann.
        return {"items": [], "offline": True, "source": None}


def _cached_barcode(code):
    entry = db.kv_get(CACHE_PREFIX + code)
    if not isinstance(entry, dict):
        return None
    if time.time() - (entry.get("ts") or 0) > CACHE_TTL:
        return None
    return entry.get("item")


def lookup_barcode(code):
    """Ein Produkt per Barcode. Eigenstaendig geschnitten, damit Phase 2
    (Kamera-Scanner) sie unveraendert weiterverwenden kann: rein der Code,
    raus das normalisierte Produkt.

    Treffer werden 30 Tage im KV-Store gecacht.
    """
    code = str(code or "").strip()
    if not code or not code.isdigit():
        return {"item": None, "offline": False, "cached": False}

    hit = _cached_barcode(code)
    if hit is not None:
        return {"item": hit, "offline": False, "cached": True}

    try:
        r = requests.get(
            PRODUCT_URL.format(code=code),
            params={"fields": ",".join(FIELDS)},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        if r.status_code == 404:
            return {"item": None, "offline": False, "cached": False}
        r.raise_for_status()
        data = r.json()
    except Exception:
        return {"item": None, "offline": True, "cached": False}

    if data.get("status") != 1:
        return {"item": None, "offline": False, "cached": False}

    item = _normalize(data.get("product"))
    if item is None:
        return {"item": None, "offline": False, "cached": False}
    item.pop("_lang", None)
    item.pop("_countries", None)
    item["code"] = item["code"] or code

    db.kv_set(CACHE_PREFIX + code, {"ts": time.time(), "item": item})
    return {"item": item, "offline": False, "cached": False}
