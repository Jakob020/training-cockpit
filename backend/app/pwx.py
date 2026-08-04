"""PWX-Export fuer TrainingPeaks.

TrainingPeaks akzeptiert im Kalender-Upload keine .ics, aber unter anderem
.pwx — das offene TrainingPeaks-XML-Format, das strukturierte Workouts
inklusive Intervalle traegt. Eine hochgeladene .pwx erscheint in TP als
geplantes Workout am gewaehlten Datum und laesst sich von dort strukturiert
auf ein Wahoo/Garmin uebertragen.

Aus der Freitext-Intervallstruktur des Plans (z. B. "3x15 min @88-94 % FTP ·
5 min RB") extrahieren wir Segmente. Die Erkennung ist bewusst tolerant:
zaehlt Wiederholungen (`3x`), Dauer (`15 min`, `1 h`, `40 s`), Intensitaeten
(`88-94 %`, `@105 %`) und Recovery ("RB", "min RB", "min Pause") und baut
daraus Warmup + N * (Work + Recovery) + Cooldown. Kann der Parser nichts
Sicheres ableiten, gibt er ein einzelnes Segment ueber die volle Dauer mit
den Grenzen aus `ftpLow`/`ftpHigh` aus — der Wahoo hat dann wenigstens ein
gueltiges strukturiertes Ziel.
"""
import datetime
import re
from typing import List, Tuple

from . import db, ics as ics_mod

# ---------------------------------------------------------------------------
# Intervall-Parser
# ---------------------------------------------------------------------------
UNIT_SECONDS = {"s": 1, "sek": 1, "sec": 1, "min": 60, "m": 60, "h": 3600, "std": 3600}
RECOVERY_HINTS = ("rb", "pause", "recovery", "erholung", "locker")


def _sec(value: float, unit: str) -> int:
    """Wandelt eine Dauer + Einheit in Sekunden."""
    return int(round(value * UNIT_SECONDS.get(unit.lower(), 60)))


def _find_durations(text: str) -> List[Tuple[float, str]]:
    """Findet alle Dauer-Angaben wie '15 min', '1 h', '40 s' im Text."""
    return [(float(v.replace(",", ".")), u.lower())
            for v, u in re.findall(r"(\d+(?:[.,]\d+)?)\s*(min|sek|sec|s|std|h|m)\b", text, re.I)]


def _find_intensities(text: str) -> List[Tuple[int, int]]:
    """Findet '88-94 %', '@105 %' etc. — gibt (low, high) je Fundstelle."""
    hits: List[Tuple[int, int]] = []
    for a, b in re.findall(r"(\d{2,3})\s*[-\u2013]\s*(\d{2,3})\s*%", text):
        hits.append((int(a), int(b)))
    for v in re.findall(r"@\s*(\d{2,3})\s*%", text):
        hits.append((int(v), int(v)))
    return hits


def _parse_segments(day: dict) -> List[dict]:
    """Baut eine Liste von Segmenten aus einer Ride-Tageszeile.

    Rueckgabe: [{name, seconds, ftp_low, ftp_high, is_recovery}, ...]
    """
    text = str(day.get("intervals") or "")
    dur_h = float(day.get("duration") or 0)
    total_s = int(round(dur_h * 3600))
    ftp_low = int(day.get("ftpLow") or 60)
    ftp_high = int(day.get("ftpHigh") or 75)

    # Wiederholungen "3x" oder "3 x" oder "3×"
    m_reps = re.search(r"(\d+)\s*[x\u00d7]\s*", text)
    reps = int(m_reps.group(1)) if m_reps else 0

    durations = _find_durations(text)
    intensities = _find_intensities(text)

    segments: List[dict] = []

    if reps >= 2 and durations:
        # Erste Dauer = Work, zweite (falls) = Recovery
        work_val, work_unit = durations[0]
        work_s = _sec(work_val, work_unit)
        rec_s = None
        for i, (v, u) in enumerate(durations[1:], start=1):
            tail = text.lower().split()
            # Heuristik: wenn irgendwo in Naehe "RB"/"Pause" steht, ist es Recovery
            if any(h in text.lower() for h in RECOVERY_HINTS):
                rec_s = _sec(v, u)
                break
        if rec_s is None:
            rec_s = max(60, int(work_s * 0.4))  # Fallback: 40 % der Arbeitsdauer

        # Intensitaet fuer die Arbeit
        if intensities:
            work_low, work_high = intensities[0]
        else:
            work_low, work_high = ftp_low, ftp_high
        rec_low, rec_high = 45, 60  # locker

        # Warmup / Cooldown aus Restzeit
        block_total = reps * (work_s + rec_s)
        remaining = max(0, total_s - block_total)
        warmup_s = int(remaining * 0.6)
        cooldown_s = remaining - warmup_s
        if warmup_s >= 300:
            segments.append({
                "name": "Warmup", "seconds": warmup_s,
                "ftp_low": 50, "ftp_high": 65, "is_recovery": True,
            })
        for i in range(reps):
            segments.append({
                "name": f"Intervall {i + 1}/{reps}", "seconds": work_s,
                "ftp_low": work_low, "ftp_high": work_high, "is_recovery": False,
            })
            # letzte Recovery weglassen, falls sie sonst den Ride kuenstlich verlaengert
            if i < reps - 1 or cooldown_s < 120:
                segments.append({
                    "name": "Erholung", "seconds": rec_s,
                    "ftp_low": rec_low, "ftp_high": rec_high, "is_recovery": True,
                })
        if cooldown_s >= 300:
            segments.append({
                "name": "Cooldown", "seconds": cooldown_s,
                "ftp_low": 45, "ftp_high": 60, "is_recovery": True,
            })
    else:
        # Kein sicheres Intervallmuster — ein Segment ueber die volle Dauer
        segments.append({
            "name": day.get("name") or "Einheit",
            "seconds": max(600, total_s),
            "ftp_low": ftp_low, "ftp_high": ftp_high,
            "is_recovery": ftp_high <= 60,
        })

    return segments


# ---------------------------------------------------------------------------
# PWX-Serializer
# ---------------------------------------------------------------------------
def _xml_escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _pwx_for_day(day: dict, iso_date: str, ftp: int) -> str:
    """Baut den PWX-Body fuer eine Rad-Einheit."""
    segments = _parse_segments(day)
    name = day.get("name") or "Radeinheit"
    zone = day.get("zone") or ""
    intervals_text = day.get("intervals") or ""

    # ftp % -> Watt (fuer target-Werte im PWX)
    def w(pct: int) -> int:
        return int(round(ftp * pct / 100))

    # Datum als naiv-Timestamp fuer PWX. TrainingPeaks liest daraus den Plantag.
    date_iso = f"{iso_date}T06:00:00"

    parts = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append('<pwx xmlns="http://www.peaksware.com/PWX/1/0" creator="Training Cockpit" version="1.0">')
    parts.append("  <workout>")
    parts.append(f"    <athlete><name>Training Cockpit</name></athlete>")
    parts.append(f"    <sportType>Bike</sportType>")
    parts.append(f"    <cmt>{_xml_escape(zone + ' — ' + intervals_text)}</cmt>")
    parts.append(f"    <code>{_xml_escape(name)}</code>")
    parts.append(f"    <time>{date_iso}</time>")

    offset = 0
    for seg in segments:
        dur = seg["seconds"]
        low = w(seg["ftp_low"])
        high = w(seg["ftp_high"])
        avg = int(round((low + high) / 2))
        parts.append("    <segment>")
        parts.append(f"      <name>{_xml_escape(seg['name'])}</name>")
        parts.append("      <summarydata>")
        parts.append(f'        <beginning>{offset}</beginning>')
        parts.append(f'        <duration>{dur}</duration>')
        parts.append(f'        <pwr min="{low}" max="{high}" avg="{avg}"/>')
        parts.append("      </summarydata>")
        parts.append("    </segment>")
        offset += dur

    parts.append("  </workout>")
    parts.append("</pwx>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Sammel-Export
# ---------------------------------------------------------------------------
def compute_ride_files():
    """Fuer jeden Tag im Plan, der eine Radeinheit ist, eine .pwx-Datei bauen.

    Rueckgabe: Liste von (filename, pwx_xml_string) — sortiert nach Datum.
    """
    settings = db.kv_get("settings") or {}
    plan = db.kv_get("plan") or {}
    log = db.kv_get("log") or {}
    ftp = int(settings.get("ftp") or 283)

    events = ics_mod.compute_events()  # liefert (date, uid, ...) pro Tag mit Datum

    # Wir brauchen zusaetzlich das Roh-Day-Objekt. Also parallel neu berechnen:
    weeks = plan.get("weeks") if isinstance(plan, dict) else None
    if not weeks:
        return []

    w1s = settings.get("week1Start")
    if not w1s:
        return []

    from datetime import date, timedelta

    def _from_iso(s):
        y, m, d = map(int, s.split("-"))
        return date(y, m, d)

    def _monday_of(d):
        return d - timedelta(days=d.weekday())

    w1 = _monday_of(_from_iso(w1s))
    out = []
    for wi, week in enumerate(weeks):
        for di, planday in enumerate(week):
            the_date = w1 + timedelta(days=wi * 7 + di)
            iso = the_date.strftime("%Y-%m-%d")
            entry = log.get(iso) or {}
            d = entry.get("override") or planday
            if not isinstance(d, dict) or d.get("type") != "ride":
                continue
            xml = _pwx_for_day(d, iso, ftp)
            safe_name = (d.get("name") or "ride").replace(" ", "_").replace("/", "-")
            fname = f"{iso}_{safe_name}.pwx"
            out.append((fname, xml))
    return out


def build_zip() -> bytes:
    """Alle Ride-PWX in einer ZIP fuer den TrainingPeaks-Upload."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, xml in compute_ride_files():
            zf.writestr(fname, xml)
        # Beipackzettel als Erklaerung
        zf.writestr(
            "README.txt",
            "Training Cockpit — PWX-Export fuer TrainingPeaks\n"
            "===============================================\n\n"
            "Fuer jede Radeinheit deines 12-Wochen-Plans liegt hier eine .pwx-Datei mit\n"
            "strukturierten Intervallen (Watt-Ziele aus deiner aktuellen FTP).\n\n"
            "Upload in TrainingPeaks:\n"
            "  Kalender oben rechts das Upload-Symbol → Datei waehlen → .pwx aus dieser\n"
            "  ZIP. Die Einheit erscheint am eingebetteten Datum als geplantes Workout\n"
            "  und laesst sich strukturiert auf Wahoo/Garmin uebertragen.\n\n"
            "Krafteinheiten sind bewusst NICHT als .pwx exportiert — sie lassen sich in\n"
            "TrainingPeaks nicht strukturiert steuern und bleiben in der Cockpit-App.\n",
        )
    buf.seek(0)
    return buf.read()
