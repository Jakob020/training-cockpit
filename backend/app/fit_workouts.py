"""Binaerer FIT-Workout-Encoder fuer Intervals.icu und andere Plattformen.

Erzeugt eine .fit-Datei nach der Garmin-FIT-SDK-Spezifikation mit einer
Workout-Definition und Workout-Steps je Segment. Watt-Ziele werden als
"custom power range" hinterlegt, damit Intervals.icu sie beim Import
uebernimmt.

Struktur der Datei:
- Header (14 Byte)
- File-ID Message (type=5 workout)
- Workout Message (Name, Sport=Cycling, Anzahl Steps)
- Workout-Step Messages (je Segment: Dauer, Custom Power Low/High)
- CRC (2 Byte)
"""
import io
import re
import struct
import zipfile
from typing import List, Tuple

from . import db


# --- FIT-CRC-Tabelle (aus FIT-SDK) ------------------------------------------
CRC_TABLE = [
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
]


def _fit_crc(data: bytes) -> int:
    crc = 0
    for b in data:
        tmp = CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ CRC_TABLE[b & 0xF]
        tmp = CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ CRC_TABLE[(b >> 4) & 0xF]
    return crc


# --- Intervall-Parser (identisch zum workouts.py-Parser) --------------------
UNIT_SECONDS = {"s": 1, "sek": 1, "sec": 1, "min": 60, "m": 60, "h": 3600, "std": 3600}
RECOVERY_HINTS = ("rb", "pause", "recovery", "erholung", "locker")


def _sec(v, u):
    return int(round(v * UNIT_SECONDS.get(u.lower(), 60)))


def _find_durations(text):
    return [(float(v.replace(",", ".")), u.lower())
            for v, u in re.findall(r"(\d+(?:[.,]\d+)?)\s*(min|sek|sec|s|std|h|m)\b", text, re.I)]


def _find_intensities(text):
    hits = []
    for a, b in re.findall(r"(\d{2,3})\s*[-\u2013]\s*(\d{2,3})\s*%", text):
        hits.append((int(a), int(b)))
    for v in re.findall(r"@\s*(\d{2,3})\s*%", text):
        hits.append((int(v), int(v)))
    return hits


def _parse_segments(day):
    text = str(day.get("intervals") or "")
    dur_h = float(day.get("duration") or 0)
    total_s = int(round(dur_h * 3600))
    ftp_low = int(day.get("ftpLow") or 60)
    ftp_high = int(day.get("ftpHigh") or 75)

    m_reps = re.search(r"(\d+)\s*[x\u00d7]\s*", text)
    reps = int(m_reps.group(1)) if m_reps else 0
    durations = _find_durations(text)
    intensities = _find_intensities(text)

    segments = []
    if reps >= 2 and durations:
        work_val, work_unit = durations[0]
        work_s = _sec(work_val, work_unit)
        rec_s = None
        for v, u in durations[1:]:
            if any(h in text.lower() for h in RECOVERY_HINTS):
                rec_s = _sec(v, u); break
        if rec_s is None:
            rec_s = max(60, int(work_s * 0.4))
        if intensities:
            work_low, work_high = intensities[0]
        else:
            work_low, work_high = ftp_low, ftp_high

        block_total = reps * (work_s + rec_s)
        remaining = max(0, total_s - block_total)
        warmup_s = int(remaining * 0.6)
        cooldown_s = remaining - warmup_s
        if warmup_s >= 300:
            segments.append({"name": "Warmup", "seconds": warmup_s,
                             "ftp_low": 50, "ftp_high": 65, "intensity": 1})
        for i in range(reps):
            segments.append({"name": f"Intervall {i+1}", "seconds": work_s,
                             "ftp_low": work_low, "ftp_high": work_high, "intensity": 0})
            if i < reps - 1 or cooldown_s < 120:
                segments.append({"name": "Erholung", "seconds": rec_s,
                                 "ftp_low": 45, "ftp_high": 60, "intensity": 2})
        if cooldown_s >= 300:
            segments.append({"name": "Cooldown", "seconds": cooldown_s,
                             "ftp_low": 45, "ftp_high": 60, "intensity": 3})
    else:
        segments.append({"name": day.get("name") or "Einheit",
                         "seconds": max(600, total_s),
                         "ftp_low": ftp_low, "ftp_high": ftp_high, "intensity": 0})
    return segments


# --- FIT-Message-Encoder ----------------------------------------------------
def _pad_string(s: str, length: int) -> bytes:
    """FIT-Strings: fixed length, null-terminated, UTF-8."""
    encoded = s.encode("utf-8")[:length - 1]
    return encoded + b"\x00" * (length - len(encoded))


def _build_fit(day, ftp: int) -> bytes:
    """Baut eine binaere FIT-Datei fuer einen Radtag."""
    segments = _parse_segments(day)
    workout_name = (day.get("name") or "Radeinheit")[:15]
    num_steps = len(segments)

    body = io.BytesIO()

    # --- Definition Message: File-ID (local msg 0) --------------------------
    body.write(bytes([0x40]))
    body.write(bytes([0]))
    body.write(bytes([0]))
    body.write(struct.pack("<H", 0))          # global msg num 0 = file_id
    body.write(bytes([4]))                    # 4 fields
    body.write(bytes([0, 1, 0x00]))           # type (u8)
    body.write(bytes([1, 2, 0x84]))           # manufacturer (u16)
    body.write(bytes([2, 2, 0x84]))           # product (u16)
    body.write(bytes([4, 4, 0x86]))           # time_created (u32)

    # --- Data Message: File-ID ---------------------------------------------
    body.write(bytes([0x00]))
    body.write(bytes([5]))                    # type=5 (workout)
    body.write(struct.pack("<H", 255))        # manufacturer=development
    body.write(struct.pack("<H", 0))          # product
    body.write(struct.pack("<I", 0))          # time_created

    # --- Definition Message: Workout (local msg 1) -------------------------
    body.write(bytes([0x41]))
    body.write(bytes([0]))
    body.write(bytes([0]))
    body.write(struct.pack("<H", 26))         # global msg num 26 = workout
    body.write(bytes([3]))                    # 3 fields
    body.write(bytes([4, 1, 0x00]))           # sport (u8)
    body.write(bytes([6, 2, 0x84]))           # num_valid_steps (u16)
    body.write(bytes([8, 16, 0x07]))          # wkt_name (string 16)

    # --- Data Message: Workout ---------------------------------------------
    body.write(bytes([0x01]))
    body.write(bytes([2]))                    # sport 2 = cycling
    body.write(struct.pack("<H", num_steps))
    body.write(_pad_string(workout_name, 16))

    # --- Definition Message: Workout-Step (local msg 2) --------------------
    body.write(bytes([0x42]))
    body.write(bytes([0]))
    body.write(bytes([0]))
    body.write(struct.pack("<H", 27))         # global msg num 27 = workout_step
    body.write(bytes([6]))                    # 6 fields
    body.write(bytes([254, 2, 0x84]))         # message_index (u16)
    body.write(bytes([0, 16, 0x07]))          # wkt_step_name (string 16)
    body.write(bytes([1, 1, 0x00]))           # duration_type (u8) 0=time
    body.write(bytes([2, 4, 0x86]))           # duration_value (u32 ms)
    body.write(bytes([3, 1, 0x00]))           # target_type (u8) 4=power
    body.write(bytes([5, 4, 0x86]))           # custom_target_power_low (u32)

    # --- Data Messages: Workout-Steps --------------------------------------
    for i, seg in enumerate(segments):
        low = int(round(ftp * seg["ftp_low"] / 100))
        high = int(round(ftp * seg["ftp_high"] / 100))
        avg = int(round((low + high) / 2))
        body.write(bytes([0x02]))
        body.write(struct.pack("<H", i))
        body.write(_pad_string(seg["name"], 16))
        body.write(bytes([0]))
        body.write(struct.pack("<I", int(seg["seconds"]) * 1000))
        body.write(bytes([4]))
        body.write(struct.pack("<I", avg + 1000))

    data = body.getvalue()

    # --- Header (14 byte) --------------------------------------------------
    header = bytearray()
    header.append(14)
    header.append(0x20)
    header.extend(struct.pack("<H", 2140))
    header.extend(struct.pack("<I", len(data)))
    header.extend(b".FIT")
    hdr_crc = _fit_crc(bytes(header))
    header.extend(struct.pack("<H", hdr_crc))

    full = bytes(header) + data
    crc = _fit_crc(full)
    return full + struct.pack("<H", crc)


# --- Sammel-Export ----------------------------------------------------------
def compute_ride_files():
    settings = db.kv_get("settings") or {}
    plan = db.kv_get("plan") or {}
    log = db.kv_get("log") or {}
    ftp = int(settings.get("ftp") or 283)
    weeks = plan.get("weeks") if isinstance(plan, dict) else None
    if not weeks: return []
    w1s = settings.get("week1Start")
    if not w1s: return []

    from datetime import date, timedelta
    def _iso(s):
        y, m, d = map(int, s.split("-"))
        return date(y, m, d)
    def _mon(d): return d - timedelta(days=d.weekday())
    w1 = _mon(_iso(w1s))

    out = []
    for wi, week in enumerate(weeks):
        for di, pd in enumerate(week):
            the = w1 + timedelta(days=wi * 7 + di)
            iso = the.strftime("%Y-%m-%d")
            entry = log.get(iso) or {}
            d = entry.get("override") or pd
            if not isinstance(d, dict) or d.get("type") != "ride":
                continue
            safe = (d.get("name") or "ride").replace(" ", "_").replace("/", "-")
            fit_bytes = _build_fit(d, ftp)
            out.append((f"{iso}_{safe}.fit", fit_bytes))
    return out


def build_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, data in compute_ride_files():
            zf.writestr(fname, data)
        zf.writestr("README.txt",
            "Training Cockpit - FIT-Workout-Export\n"
            "=====================================\n\n"
            "Fuer jede Radeinheit des 12-Wochen-Plans eine .fit-Datei mit\n"
            "strukturierten Steps und Watt-Zielen (aus deiner FTP).\n\n"
            "Upload in Intervals.icu:\n"
            "  1. intervals.icu einloggen\n"
            "  2. Kalender -> 'Hochladen' oben rechts\n"
            "  3. Alle .fit-Dateien auswaehlen (mehrere gleichzeitig)\n"
            "  4. Workouts erscheinen als geplante Trainings am jeweiligen Datum\n"
            "  5. Wahoo-Sync (Athlete -> Connections) schiebt sie automatisch\n"
            "     auf den Wahoo-Kopf\n\n"
            "Krafteinheiten sind nicht enthalten - Intervals.icu und Wahoo\n"
            "koennen sie nicht strukturiert steuern.\n")
    buf.seek(0)
    return buf.read()