"""HTTP-Routen fuer das Lebensmittel-Tracking, gebuendelt in einem Router,
damit main.py schlank bleibt.

Jede schreibende Route liefert den aktualisierten Tageseintrag aus dem
``log``-Key mit zurueck (Feld ``day``). Das ist kein Luxus, sondern noetig:
das Frontend haelt ``log`` komplett im Speicher und schreibt es als ein
einziges Blob zurueck. Ohne die Rueckgabe wuerde der naechste Schreibvorgang
des Frontends die gerade berechneten Tagessummen wieder ueberbuegeln.
"""
import datetime

from fastapi import APIRouter, HTTPException, Request

from . import food, food_ai, food_store

router = APIRouter(prefix="/api/food", tags=["food"])


def _date_param(date):
    if not date:
        return datetime.date.today().isoformat()
    if not food_store._valid_date(date):
        raise HTTPException(status_code=400, detail="Ungueltiges Datum, erwartet YYYY-MM-DD")
    return date


# -------------------------------- Suche --------------------------------------
@router.get("/search")
def search(q: str = "", page_size: int = 20):
    return food.search(q, page_size)


@router.get("/barcode/{code}")
def barcode(code: str):
    res = food.lookup_barcode(code)
    if res["item"] is None and not res["offline"]:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    return res


# ----------------------- KI-Schaetzung (selbstgemacht) -----------------------
@router.get("/ai-status")
def ai_status():
    """Die Oberflaeche blendet die Funktion aus, wenn kein Schluessel liegt —
    besser als ein Knopf, der nur Fehler produziert."""
    return {"available": food_ai.available()}


@router.post("/ai-estimate")
async def ai_estimate(request: Request):
    body = await request.json()
    return food_ai.estimate(body.get("text"))


# ------------------------------- Tageslog ------------------------------------
@router.get("/log")
def get_log(date: str = ""):
    return food_store.get_day(_date_param(date))


@router.post("/log")
async def post_log(request: Request):
    body = await request.json()
    date = _date_param(body.get("date"))
    return food_store.add_entry(date, body)


@router.patch("/log/{entry_id}")
async def patch_log(entry_id: str, request: Request):
    body = await request.json()
    date = _date_param(body.get("date"))
    res = food_store.update_entry(date, entry_id, body)
    if res is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    return res


@router.delete("/log/{entry_id}")
def delete_log(entry_id: str, date: str = ""):
    res = food_store.delete_entry(_date_param(date), entry_id)
    if res is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    return res


@router.post("/log/recipe")
async def post_log_recipe(request: Request):
    body = await request.json()
    date = _date_param(body.get("date"))
    res = food_store.book_recipe(
        date, body.get("recipe_id"), body.get("portionen"), body.get("meal"),
    )
    if res is None:
        raise HTTPException(status_code=404, detail="Rezept nicht gefunden")
    return res


# ----------------------- Zuletzt / Favoriten / Eigene ------------------------
@router.get("/recent")
def get_recent():
    return {"items": food_store.get_recent()}


@router.get("/favorites")
def get_favorites():
    return {"items": food_store.get_favorites()}


@router.post("/favorites")
async def post_favorites(request: Request):
    return {"items": food_store.add_favorite(await request.json())}


@router.delete("/favorites/{key:path}")
def delete_favorites(key: str):
    return {"items": food_store.delete_favorite(key)}


@router.get("/custom")
def get_custom():
    return {"items": food_store.get_custom()}


@router.post("/custom")
async def post_custom(request: Request):
    return {"item": food_store.add_custom(await request.json())}


@router.delete("/custom/{item_id}")
def delete_custom(item_id: str):
    return {"items": food_store.delete_custom(item_id)}


# -------------------------------- Rezepte ------------------------------------
def _with_totals(r):
    """Rezept plus abgeleitete Werte — die Oberflaeche soll nicht rechnen."""
    return {**r, "info": food_store.recipe_per_portion(r)}


@router.get("/recipes")
def get_recipes():
    return {"items": [_with_totals(r) for r in food_store.get_recipes()]}


@router.post("/recipes")
async def post_recipes(request: Request):
    return {"item": _with_totals(food_store.save_recipe(await request.json()))}


@router.put("/recipes/{recipe_id}")
async def put_recipes(recipe_id: str, request: Request):
    saved = food_store.save_recipe(await request.json(), recipe_id)
    if saved is None:
        raise HTTPException(status_code=404, detail="Rezept nicht gefunden")
    return {"item": _with_totals(saved)}


@router.delete("/recipes/{recipe_id}")
def delete_recipes(recipe_id: str):
    return {"items": [_with_totals(r) for r in food_store.delete_recipe(recipe_id)]}
