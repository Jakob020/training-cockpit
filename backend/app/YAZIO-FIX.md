# Yazio-Sync — Fix fuer falsche Werte

## Was war los

Der Sync hat "195 Tage" gemeldet, aber pro Tag falsche Zahlen geschrieben
(kcal 193, Protein 145, Carbs 261). Ursache: der erste Parser hat pro Tag "das
erste beste numerische Feld" genommen — das war teils ein Zielwert, teils der
Energiegehalt eines einzelnen Produkts.

## Was jetzt anders ist

`backend/app/yazio.py` extrahiert die Makros gezielt:

1. Zuerst echte Tagesfelder (`consumed_energy`, `consumed_nutrients`, …).
2. Ist nichts da: Summe ueber die Items eines Tages (jedes Produkt einzeln).
3. Zielwerte (`*_goal`) werden ignoriert, wenn Ist-Werte da sind. Nur als
   letzter Rueckfall gelten sie ueberhaupt.
4. Plausibilitaets-Check: Tageswerte < 50 kcal werden verworfen.

Zusaetzlich schreibt jeder Sync die Rohdaten nach
`<DB_DIR>/yazio_last_dump.json`, und der neue Endpunkt

```
GET /api/yazio/dump/2026-08-04
```

zeigt das Roh-JSON fuer einen Tag plus die geparsten Werte.

## Was du tun musst

1. Die Aenderungen committen und pushen:

```
cd ~/Claude/Projects/training-cockpit
git add -A && git commit -m "Yazio-Parser: praezise Tagessummen" && git push
```

2. Container neu bauen:

```
docker compose up -d --build
```

3. Alte falsche Werte einmal loeschen und neu ziehen. Am schnellsten in der App
   unter Setup ganz unten "Alle Daten loeschen" waehlen (loescht auch den Plan;
   dafuer bekommst du die Standardwerte zurueck), dann Setup → Yazio → "Jetzt
   synchronisieren".

   Wenn du Plan/Einstellungen behalten willst, loesche nur das Log per curl:

```
curl -X DELETE http://localhost:8000/api/kv/log
```

   Danach in der App den Sync neu anstossen.

4. Kontrolle: Setup → Yazio → "Jetzt synchronisieren". Danach in der Heute-
   Ansicht pruefen, ob kcal, Protein, Carbs, Fett zu deinem Yazio-Tagesreport
   passen. Sind sie immer noch falsch, oeffne:

```
http://localhost:8000/api/yazio/dump/2026-08-04
```

   und schick mir die Ausgabe. Am `raw`-Feld sehen wir, wie Yazio den Tag heute
   nennt und passen die Aliasse in `MACRO_ALIASES` (oben in `yazio.py`) an.
