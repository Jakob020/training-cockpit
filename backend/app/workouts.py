"""Workout-Export in TCX + ZWO - nur mit geplanten Werten aus dem Cockpit."""
import re
from typing import List, Tuple
from . import db

UNIT_SECONDS = {"s": 1, "sek": 1, "sec": 1, "min": 60, "m": 60, "h": 3600, "std": 3600}
RECOVERY_HINTS = ("rb", "pause", "recovery", "erholung", "locker")


def _sec(v, u): return int(round(v * UNIT_SECONDS.get(u.lower(), 60)))


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
                             "ftp_low": 50, "ftp_high": 65, "kind": "warmup"})
        for i in range(reps):
            segments.append({"name": f"Intervall {i+1}/{reps}", "seconds": work_s,
                             "ftp_low": work_low, "ftp_high": work_high, "kind": "work"})
            if i < reps - 1 or cooldown_s < 120:
                segments.append({"name": "Erholung", "seconds": rec_s,
                                 "ftp_low": 45, "ftp_high": 60, "kind": "recovery"})
        if cooldown_s >= 300:
            segments.append({"name": "Cooldown", "seconds": cooldown_s,
                             "ftp_low": 45, "ftp_high": 60, "kind": "cooldown"})
    else:
        segments.append({"name": day.get("name") or "Einheit",
                         "seconds": max(600, total_s),
                         "ftp_low": ftp_low, "ftp_high": ftp_high, "kind": "steady"})
    return segments


def _default_fuel_rates(day):
    dur_h = float(day.get("duration") or 0)
    mid = ((day.get("ftpLow") or 60) + (day.get("ftpHigh") or 75)) / 2
    if mid < 65 and dur_h < 2:
        return {"carbs_g_h": 40, "fluid_ml_h": 600, "sodium_mg_h": 500}
    if mid < 100:
        return {"carbs_g_h": 78, "fluid_ml_h": 775, "sodium_mg_h": 850}
    if mid < 115:
        return {"carbs_g_h": 90, "fluid_ml_h": 800, "sodium_mg_h": 900}
    if dur_h >= 2.5:
        return {"carbs_g_h": 90, "fluid_ml_h": 800, "sodium_mg_h": 1000}
    return {"carbs_g_h": 60, "fluid_ml_h": 700, "sodium_mg_h": 700}


def _fuel_targets_for_day(day):
    dur_h = float(day.get("duration") or 0)
    fuel = day.get("fuel") or {}
    rc = fuel.get("carbsPerHour") or fuel.get("carbs_g_h")
    rf = fuel.get("fluidPerHour") or fuel.get("fluid_ml_h")
    rs = fuel.get("sodiumPerHour") or fuel.get("sodium_mg_h")
    tc = fuel.get("carbsTotal") or fuel.get("carbs_g")
    tf = fuel.get("fluidTotal") or fuel.get("fluid_ml") or fuel.get("fluid_l")
    ts = fuel.get("sodiumTotal") or fuel.get("sodium_mg") or fuel.get("sodium_g")
    if rc is None or rf is None or rs is None:
        fb = _default_fuel_rates(day)
        rc = rc or fb["carbs_g_h"]; rf = rf or fb["fluid_ml_h"]; rs = rs or fb["sodium_mg_h"]
    if tc is None: tc = round(rc * dur_h)
    if tf is None: tf = round(rf * dur_h)
    if ts is None: ts = round(rs * dur_h)
    return {"carbs_g_h": int(round(rc)), "fluid_ml_h": int(round(rf)),
            "sodium_mg_h": int(round(rs)),
            "carbs_g_total": int(round(tc)), "fluid_ml_total": int(round(tf)),
            "sodium_mg_total": int(round(ts))}


def _plan_totals(segments):
    total_s = sum(int(s["seconds"]) for s in segments if s.get("seconds", 0) > 0)
    if total_s == 0: return {"seconds": 0}
    weighted = sum(((s["ftp_low"] + s["ftp_high"]) / 2) * s["seconds"] for s in segments)
    return {"seconds": total_s, "avg_pct_ftp": weighted / total_s}


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _min(s): return int(round(s / 60))


def _tcx_for_day(day, iso_date, ftp):
    segs = _parse_segments(day)
    t = _plan_totals(segs)
    f = _fuel_targets_for_day(day)
    name = (day.get("name") or "Radeinheit")[:15]
    itxt = day.get("intervals") or ""
    notes = (f"Geplante Dauer: {_min(t.get('seconds', 0))} min | "
             f"mittlere Intensitaet ~{t.get('avg_pct_ftp', 0):.0f} % FTP | "
             f"Fueling: {f['carbs_g_h']} g/h Carbs ({f['carbs_g_total']} g) | "
             f"{f['fluid_ml_h']} ml/h Fluid ({f['fluid_ml_total']} ml) | "
             f"{f['sodium_mg_h']} mg/h Natrium ({f['sodium_mg_total']} mg) | "
             f"Struktur: {itxt}")
    p = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<TrainingCenterDatabase '
         'xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" '
         'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
         '  <Workouts>', f'    <Biking Name="{_esc(name)}">']
    for i, s in enumerate(segs):
        lo = int(round(ftp * s["ftp_low"] / 100))
        hi = int(round(ftp * s["ftp_high"] / 100))
        intens = "Resting" if s["kind"] in ("recovery", "cooldown") else "Active"
        p += [f'      <Step xsi:type="Step_t"><StepId>{i+1}</StepId>',
              f'        <Name>{_esc(s["name"])[:15]}</Name>',
              f'        <Duration xsi:type="Time_t"><Seconds>{int(s["seconds"])}</Seconds></Duration>',
              f'        <Intensity>{intens}</Intensity>',
              '        <Target xsi:type="PowerZone_t">',
              '          <PowerZone xsi:type="CustomPowerZone_t">',
              f'            <Low>{lo}</Low><High>{hi}</High>',
              '          </PowerZone></Target></Step>']
    p += [f'      <ScheduledOn>{iso_date}</ScheduledOn>',
          f'      <Notes>{_esc(notes)}</Notes>',
          '    </Biking></Workouts></TrainingCenterDatabase>']
    return "\n".join(p)


def _zwo_for_day(day, ftp):
    segs = _parse_segments(day)
    t = _plan_totals(segs)
    f = _fuel_targets_for_day(day)
    name = day.get("name") or "Radeinheit"
    itxt = day.get("intervals") or ""
    desc = (f"{itxt} | Dauer geplant: {_min(t.get('seconds', 0))} min | "
            f"mittl. Intensitaet ~{t.get('avg_pct_ftp', 0):.0f} % FTP | "
            f"Fueling: {f['carbs_g_h']} g/h Carbs ({f['carbs_g_total']} g), "
            f"{f['fluid_ml_h']} ml/h Fluid ({f['fluid_ml_total']} ml), "
            f"{f['sodium_mg_h']} mg/h Natrium ({f['sodium_mg_total']} mg)")
    p = ['<workout_file>', f'  <author>Training Cockpit</author>',
         f'  <name>{_esc(name)}</name>',
         f'  <description>{_esc(desc)}</description>',
         '  <sportType>bike</sportType>', '  <tags/>', '  <workout>',
         f'    <textevent timeoffset="0" message="Fueling geplant: '
         f'{f["carbs_g_h"]} g/h Carbs, {f["fluid_ml_h"]} ml/h, '
         f'{f["sodium_mg_h"]} mg/h Natrium"/>']
    for s in segs:
        lo = s["ftp_low"] / 100.0; hi = s["ftp_high"] / 100.0
        d = int(s["seconds"]); k = s["kind"]
        if k == "warmup":
            p.append(f'    <Warmup Duration="{d}" PowerLow="{lo:.2f}" PowerHigh="{hi:.2f}"/>')
        elif k == "cooldown":
            p.append(f'    <Cooldown Duration="{d}" PowerLow="{hi:.2f}" PowerHigh="{lo:.2f}"/>')
        elif k == "recovery":
            avg = (lo + hi) / 2
            p.append(f'    <SteadyState Duration="{d}" Power="{avg:.2f}"><textevent timeoffset="0" message="Erholung"/></SteadyState>')
        elif k == "work":
            avg = (lo + hi) / 2
            p.append(f'    <SteadyState Duration="{d}" Power="{avg:.2f}"><textevent timeoffset="0" message="{_esc(s["name"])}"/></SteadyState>')
        else:
            avg = (lo + hi) / 2
            p.append(f'    <SteadyState Duration="{d}" Power="{avg:.2f}"/>')
    p += ['  </workout>', '</workout_file>']
    return "\n".join(p)


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
        y, m, d = map(int, s.split("-")); return date(y, m, d)
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
            out.append((f"tcx/{iso}_{safe}.tcx", _tcx_for_day(d, iso, ftp)))
            out.append((f"zwo/{iso}_{safe}.zwo", _zwo_for_day(d, ftp)))
    return out


def build_zip():
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, xml in compute_ride_files():
            zf.writestr(fname, xml)
        zf.writestr("README.txt",
            "Training Cockpit - Workout-Export (TCX + ZWO)\n"
            "=============================================\n\n"
            "Enthaelt NUR geplante Werte:\n"
            "  - Dauer je Block\n"
            "  - Watt-Ziele (FTP x %-Bereich)\n"
            "  - Fueling: Carbs g/h, Fluid ml/h, Natrium mg/h + Gesamtsummen\n\n"
            "Keine Distanz, keine Kalorien - die entstehen erst beim Fahren.\n\n"
            "Upload:\n"
            "  tcx/ -> TrainingPeaks (Kalender -> Upload-Symbol -> .tcx)\n"
            "  zwo/ -> Zwift, TrainerRoad, Wahoo (Watt als FTP-Anteil)\n")
    buf.seek(0)
    return buf.read()