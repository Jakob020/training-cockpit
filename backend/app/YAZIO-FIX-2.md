# Yazio-Fix (2) — auf reale Feldstruktur zugeschnitten

## Erkenntnis aus deinem Dump

Yazio benutzt Punkt-Notation (`energy.energy`, `nutrient.protein`, `nutrient.carb`,
`nutrient.fat`) und liefert die Tagessumme NICHT direkt. Sie steht verteilt in
`daily_summary.meals.{breakfast,lunch,dinner,snack}.nutrients`.

Die grossen Werte, die du vorher gesehen hast (kcal 2574, Protein 145), waren
`daily_summary.goals` — also Zielwerte, keine Ist-Werte.

## Was der neue Parser macht

`backend/app/yazio.py`:

1. Summiert die Ist-Werte aus `daily_summary.meals[*].nutrients` (Ist).
2. Ignoriert alle `goals` / `goal` / `target`-Container.
3. Faellt auf einen defensiven Baumscan zurueck, wenn Yazio das Layout
   irgendwann aendert. Zielwerte werden dabei explizit uebersprungen.

## Offline gegen deinen Dump verifiziert

    parsed = {'kcal': 1034, 'protein': 98, 'carbs': 96, 'fat': 25}

Das ist die Summe deiner heutigen Mahlzeiten laut Yazio:

    Fruehstueck: 470.9 kcal / 51.99 P / 35.23 C / 11.9 F
    Mittag:      332.0 kcal / 40.00 P / 24.40 C /  6.4 F
    Snack:       231.25 kcal /  6.38 P / 36.25 C /  6.38 F
    Abendessen:    0.00 kcal /  0.00 P /  0.00 C /  0.0 F
    Summe:      1034.15 kcal / 98.37 P / 95.88 C / 24.68 F

## Zu den "58 g Protein"

Vergleicht man das mit dem, was Yazio in `meals` gebucht hat, steckt der
Unterschied direkt in den Yazio-Daten: dort ist ein Frueh-Eintrag mit 52 g
Protein enthalten, plus 40 g im Mittag, plus 6 g im Snack. Wenn dein Yazio-
Feed in der App diese Eintraege heute wirklich enthaelt, ist 98 g die korrekte
Tagessumme. Der Wert wird sich aendern, wenn du Yazio-Eintraege loeschst oder
korrigierst — dann bei einem naechsten Sync werden auch die Cockpit-Werte
angepasst.

## Was du jetzt tust

```
cd ~/Claude/Projects/training-cockpit
git add -A && git commit -m "Yazio-Parser: reale meals-Struktur" && git push
docker compose up -d --build
curl -X DELETE http://localhost:8000/api/kv/log
```

Dann in der App unter Setup → Yazio → "Jetzt synchronisieren" — und in der
Heute-Ansicht pruefen. Erwartet werden fuer heute ~1034 kcal, 98 g Protein,
96 g Carbs, 25 g Fett.

## Wenn Yazio in der App andere Werte anzeigt

Dann liegt es an den Yazio-Rohdaten, nicht am Parser. Kontrolle:

```
curl -s http://localhost:8000/api/yazio/dump/2026-08-04 | python3 -m json.tool
```

Vergleiche `raw.daily_summary.meals` mit dem, was du in der Yazio-App siehst.
Weichen die Werte dort schon voneinander ab, ist der Yazio-Server noch nicht
synchron mit deinen App-Eintraegen — dann kurz warten und den Sync wiederholen.
