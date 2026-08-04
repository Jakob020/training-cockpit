# Training Cockpit

Selbstgehostetes, tägliches Trainings-Dashboard für einen 12-Wochen-Block (Sweet Spot → Schwelle → VO2max), mit Watt-Zielen aus der FTP, Kraftplan, Ernährungs-Tracking und Gewichtstrend. Server-Version der ursprünglichen Sandbox-App: die Persistenz läuft jetzt über ein FastAPI-Backend mit SQLite, plus zwei Integrationen — **Yazio-Sync** (automatisch täglich) und **TrainingPeaks-Export** (nur geänderte Tage).

## Was diese Version kann

- **Cockpit-Ansicht** pro Tag: Watt-Ziele, Fuel-Bedarf, Kraft-Session, Ernährungsziele, Gewicht/Notiz.
- **Individuelle Tages-Einheit:** „Einheit für heute ersetzen" erlaubt eine komplett frei zusammengestellte Einheit — bei Kraft mit eigenen Übungen inkl. Sätzen und Wdh., bei Rad mit eigener Struktur. Gilt nur für diesen Tag, der Grundplan bleibt unangetastet.
- **Auswertung:** Gewichtstrend mit Ampel, Fortschritt zum Ziel, Wochenbilanz, Makro-Bilanz (kcal/Protein/Carbs/Fett) der letzten 7 Tage, Kraft-Verlauf.
- **Yazio-Sync (automatisch):** einmal täglich am Tagesende zieht der Server deine Tageswerte und schreibt kcal/Protein/Carbs/Fett in die betroffenen Tage.
- **TrainingPeaks-Export (kostenlos):** `.ics`-Export **nur der geänderten Tage**, jeder Tag mit stabiler UID → Re-Import überschreibt genau diese Tage in TrainingPeaks, der Rest bleibt unberührt.

## Architektur

```
Browser ──▶ FastAPI (uvicorn, :8000)
              ├── /api/kv/*       JSON-Blobs (settings, plan, nutrition, strength, log)  → SQLite
              ├── /api/yazio/*    manueller/automatischer Yazio-Sync
              ├── /api/tp/ics     Kalender-Export (scope=all|changed)
              └── /               ausgeliefertes React-Frontend (Vite-Build)
            └── APScheduler       täglicher Yazio-Job am Tagesende
```

Ein einziger Container baut das Frontend und serviert es zusammen mit der API. SQLite liegt im Volume `/data`.

## Schnellstart

```bash
cp .env.example .env        # Yazio-Zugangsdaten & Sync-Zeit eintragen
docker compose up -d --build
# App: http://localhost:8000
```

Für den Betrieb im Netz (Kalender-Abo, PWA-Icon) hinter HTTPS: den `caddy`-Block in `docker-compose.yml` einkommentieren und die Domain in `Caddyfile` setzen.

### Lokal ohne Docker (Entwicklung)

```bash
# Backend
cd backend && pip install -r requirements.txt
DB_PATH=./cockpit.db uvicorn app.main:app --reload
# Frontend (zweites Terminal)
cd frontend && npm install && npm run dev   # Vite proxyt /api an :8000
```

## Auf GitHub pushen

Das Repository ist bereits lokal initialisiert und committet. Ich kann von hier aus nicht selbst pushen (kein Netzzugang, keine Zugangsdaten). So schiebst du es hoch:

1. Auf github.com ein **leeres** Repo anlegen (ohne README/License), z. B. `training-cockpit`.
2. Im Projektordner:

```bash
git remote add origin git@github.com:DEIN-USER/training-cockpit.git
git branch -M main
git push -u origin main
```

(HTTPS statt SSH: `https://github.com/DEIN-USER/training-cockpit.git`.)

## TrainingPeaks-Workflow

1. In der App unter **Setup → TrainingPeaks** auf „Nur geänderte Tage" tippen → `.ics` wird heruntergeladen (die Zahl zeigt, wie viele Tage sich seit dem letzten Export geändert haben).
2. In TrainingPeaks: Kalender → Datei importieren.
3. Weil jeder Tag eine feste UID hat, werden nur diese Tage überschrieben. „Alle Tage" exportiert den kompletten Block (z. B. beim ersten Mal).

Rad-Events enthalten Watt-Ziele, Intervalle und Zone; Kraft-Events die Übungen mit Sätzen×Wdh. Reine Ruhetage kommen als „Ruhetag"-Event mit, damit ein Wechsel Training→Ruhe den alten Eintrag sauber überschreibt.

> Hinweis: Strukturierte TrainingPeaks-Workouts (die dein Gerät steuern) gehen nur über die Partner-API, die für Privatnutzung nicht offen ist. Der `.ics`-Weg ist der kostenlose, praktikable Ersatz für die Kalenderansicht. Für gerätesteuernde Bike-Intervalle wäre ein `.zwo`/`.erg`-Export je Einheit sinnvoll — leicht ergänzbar, sobald das Intervall-Datenmodell strukturiert ist (heute Freitext).

## Yazio-Sync — wichtige Hinweise (inoffiziell)

Yazio hat **keine offizielle API**. Der Sync nutzt das Community-Tool [`yazio-exporter`](https://pypi.org/project/yazio-exporter/), das sich mit E-Mail/Passwort gegen Yazios private API einloggt.

- **Undokumentiert und änderbar:** Wenn ein Sync 0 oder falsche Werte schreibt, hat sich vermutlich die Feldbenennung geändert. In `backend/app/yazio.py` die `MACRO_KEYS`-Regexe anpassen. Der Parser sucht defensiv nach den ersten passenden numerischen Feldern je Tag.
- **Kein 2FA:** Mit aktivierter Zwei-Faktor-Authentifizierung schlägt der Passwort-Login fehl.
- **Smart-Tracking/KI-Mahlzeiten** sind im Export teils nicht enthalten.
- **AGB:** nur für den Eigengebrauch gedacht. Zugangsdaten liegen ausschließlich in `.env` (nicht im Image, nicht im Repo).
- Läuft ein Sync-Fehler auf, zeigt Setup → Yazio die letzte Fehlermeldung; der manuelle Import (Werte einfügen) bleibt als Fallback.

## Datenmigration aus der Sandbox-Version

Die Storage-Keys sind identisch (`settings`, `plan`, `nutrition`, `strength`, `log`). Wenn du aus der alten Artefakt-Version Daten hast, kannst du sie über die KV-Endpunkte einspielen, z. B.:

```bash
curl -X PUT http://localhost:8000/api/kv/log \
  -H 'Content-Type: application/json' \
  -d '{"value": { ... dein Log-JSON ... }}'
```

## Projektstruktur

```
training-cockpit/
├── Dockerfile              # baut Frontend, serviert Backend + Static
├── docker-compose.yml
├── Caddyfile               # optionales HTTPS
├── .env.example
├── backend/
│   ├── requirements.txt
│   └── app/
│       ├── main.py         # FastAPI-Routen + Scheduler
│       ├── db.py           # SQLite-KV-Store
│       ├── ics.py          # Kalender-Export + Changed-Day-Diff
│       └── yazio.py        # inoffizieller Yazio-Sync
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── index.html
    ├── public/manifest.webmanifest
    └── src/
        ├── main.jsx
        └── App.jsx         # das Dashboard (Storage → API)
```

## Offene Punkte / Ehrlichkeit

Dieses Projekt ist ein vollständiges, lauffähig aufgebautes Gerüst, das ich hier nicht end-to-end testen konnte (kein Netz, kein Docker-Build in dieser Umgebung). Zwei Stellen brauchen erfahrungsgemäß einen Blick beim ersten Lauf: die Yazio-Feldzuordnung (siehe oben) und ggf. das `yazio-exporter`-CLI-Verhalten (Login/Ausgabeformat). Beides ist klar isoliert in `backend/app/yazio.py`. Melde dich, wenn beim ersten `docker compose up` etwas klemmt — dann ziehe ich es gerade.
