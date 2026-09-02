"""Naehrwert-Schaetzung fuer selbstgemachte Lebensmittel per Claude.

Warum hier ueberhaupt ein Sprachmodell steht, obwohl im Projekt sonst gilt
"feste Regeln deterministisch ausprogrammieren": Fuer "Marmelade im 3:1-
Verhaeltnis" gibt es keine berechenbare Wahrheit. Open Food Facts kennt
verpackte Produkte mit Barcode, aber keine Hausmannskost. Eine begruendete
Schaetzung ist hier das Beste, was ueberhaupt moeglich ist — und sie ist
ausdruecklich ein VORSCHLAG: die Werte landen im Formular und werden vom
Menschen bestaetigt oder korrigiert, bevor irgendetwas gespeichert wird.

Bewusste Entscheidungen:

* **Strukturierte Ausgabe statt Freitext-Parsing.** ``output_config.format``
  mit JSON-Schema garantiert gueltiges JSON; ein Regex ueber Prosa waere
  die uebliche Fehlerquelle.
* **Kein Schluessel, kein Absturz.** Ohne ``ANTHROPIC_API_KEY`` meldet
  ``available()`` schlicht False und die Oberflaeche blendet die Funktion
  aus. Der Rest der App laeuft unveraendert weiter.
* **Netzabhaengig.** Die Schaetzung braucht Verbindung. Das ist vertretbar,
  weil eigene Lebensmittel zu Hause angelegt werden und danach offline aus
  "Eigene" und "Zuletzt" verfuegbar sind.
"""
import json
import os

# Opus 5 statt Sonnet: Genauigkeit geht hier vor Kosten. Bei Hausmannskost
# mit Verhaeltnisangaben und Einkochverlusten schwanken die Schaetzungen
# spuerbar, und ein danebenliegender Wert landet ungeprueft in der Tagesbilanz.
MODEL = "claude-opus-5"
# "high" ist die Voreinstellung und der sinnvolle Punkt fuer diese Aufgabe;
# "max" waere fuer eine Naehrwertschaetzung Verschwendung.
EFFORT = "high"
MAX_INPUT_CHARS = 500
TIMEOUT = 45.0

SYSTEM = """Du schätzt Nährwerte von Lebensmitteln, überwiegend selbstgemachten.

Regeln:
- Alle Werte beziehen sich auf 100 g des fertigen, essfertigen Produkts.
- Rechne Zubereitungsverluste ein. Beim Einkochen von Marmelade verdampft
  Wasser, das Ergebnis ist energiedichter als die Summe der rohen Zutaten.
  Bei gegartem Reis oder Nudeln ist es umgekehrt.
- Verhältnisangaben wie "3:1" bei Gelierzucker meinen Frucht zu Zucker.
- Nenne den Namen kurz und wiedererkennbar, ohne Mengenangabe.
- Beschreibe in "annahmen" in einem Satz, worauf die Schätzung beruht —
  besonders die Mengen, die du unterstellt hast.
- "sicherheit" ist "hoch" bei einfachen, gut bekannten Lebensmitteln,
  "niedrig" wenn die Angabe sehr vage ist oder stark schwanken kann.
- Schätze auch bei knapper Beschreibung; sage die Unsicherheit über das
  Feld "sicherheit", nicht durch Verweigern."""

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Kurzer Name des Lebensmittels"},
        "kcal": {"type": "number", "description": "Kilokalorien je 100 g"},
        "protein": {"type": "number", "description": "Protein in g je 100 g"},
        "carbs": {"type": "number", "description": "Kohlenhydrate in g je 100 g"},
        "fat": {"type": "number", "description": "Fett in g je 100 g"},
        "annahmen": {"type": "string", "description": "Ein Satz zur Grundlage der Schätzung"},
        "sicherheit": {"type": "string", "enum": ["hoch", "mittel", "niedrig"]},
    },
    "required": ["name", "kcal", "protein", "carbs", "fat", "annahmen", "sicherheit"],
    "additionalProperties": False,
}


def available():
    """Ob die Funktion nutzbar ist. Die Oberflaeche blendet sie sonst aus,
    statt einen Knopf anzubieten, der nur Fehler produziert."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _client():
    import anthropic
    return anthropic.Anthropic(timeout=TIMEOUT)


def _plausible(data):
    """Grobe Plausibilitaet. Ein Sprachmodell kann sich verrechnen; 900 kcal
    je 100 g ist physikalisch kaum moeglich (reines Fett hat ~900), und
    negative Werte gibt es nicht."""
    for key in ("kcal", "protein", "carbs", "fat"):
        v = data.get(key)
        if not isinstance(v, (int, float)) or v < 0:
            return False
    if data["kcal"] > 950:
        return False
    # Makros koennen zusammen keine 100 g je 100 g deutlich ueberschreiten.
    if data["protein"] + data["carbs"] + data["fat"] > 105:
        return False
    return True


def estimate(text):
    """Naehrwerte je 100 g schaetzen. Gibt immer ein Dict zurueck, wirft nie.

    Erfolg:  {"ok": True, "item": {...}}
    Fehler:  {"ok": False, "error": "<Klartext fuer die Oberflaeche>"}
    """
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "Beschreibung fehlt"}
    if len(text) > MAX_INPUT_CHARS:
        text = text[:MAX_INPUT_CHARS]
    if not available():
        return {"ok": False, "error": "KI-Schätzung ist nicht eingerichtet (ANTHROPIC_API_KEY fehlt)."}

    import anthropic

    try:
        response = _client().messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            messages=[{"role": "user", "content": text}],
        )
    except anthropic.AuthenticationError:
        return {"ok": False, "error": "API-Schlüssel wird abgelehnt."}
    except anthropic.RateLimitError:
        return {"ok": False, "error": "Zu viele Anfragen — kurz warten."}
    except anthropic.APIConnectionError:
        return {"ok": False, "error": "Keine Verbindung zur KI."}
    except anthropic.APIStatusError as e:
        return {"ok": False, "error": f"KI-Fehler ({e.status_code})."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"KI-Fehler: {str(e)[:120]}"}

    if response.stop_reason == "refusal":
        return {"ok": False, "error": "Die KI hat die Anfrage abgelehnt."}

    raw = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {"ok": False, "error": "Antwort war nicht lesbar."}

    if not _plausible(data):
        return {"ok": False, "error": "Geschätzte Werte waren unplausibel — bitte von Hand eintragen."}

    return {
        "ok": True,
        "item": {
            "name": str(data["name"]).strip()[:80] or "Eigenes Lebensmittel",
            "per100": {
                "kcal": round(float(data["kcal"]), 1),
                "protein": round(float(data["protein"]), 1),
                "carbs": round(float(data["carbs"]), 1),
                "fat": round(float(data["fat"]), 1),
            },
            "annahmen": str(data["annahmen"]).strip()[:300],
            "sicherheit": data["sicherheit"],
        },
    }
