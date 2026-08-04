"""Builds the TrainingPeaks/calendar .ics feed.

Key design goals (per requirements):
- One event PER DATE, with a STABLE UID `cockpit-YYYYMMDD@trainingcockpit`.
  Re-importing an .ics with the same UID overwrites exactly that day in
  TrainingPeaks and leaves every other day untouched.
- "Changed only" export: we store a hash per day from the last export
  (kv key `tp_hashes`). scope=changed emits only days whose content changed,
  so small, late edits don't force a full-calendar re-import.
- Rest days are emitted too (as 'Ruhetag'), so that changing a training day
  into a rest day still overwrites the old event instead of leaving a stale one.
"""
import hashlib
from datetime import date, datetime, timedelta

from . import db

WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _watt(ftp, pct):
    try:
        return round(float(ftp) * float(pct) / 100)
    except (TypeError, ValueError):
        return 0


def _from_iso(s):
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)


def _monday_of(d):
    return d - timedelta(days=d.weekday())


def _esc(s):
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _phase_for_week(w):
    if w <= 3:
        return "hypertrophy"
    if w == 4:
        return "deload1"
    if w <= 7:
        return "strength"
    if w == 8:
        return "deload2"
    if w <= 11:
        return "maintenance"
    return "taper"


def _render(d, week, ftp, phases, sessions):
    t = d.get("type")
    if t == "ride":
        wl, wh = _watt(ftp, d.get("ftpLow")), _watt(ftp, d.get("ftpHigh"))
        summary = f"\U0001F6B4 {d.get('name', 'Radeinheit')} \u00b7 {d.get('duration', '')} h"
        na = d.get("sodiumPerHour")
        desc = (
            f"Zone {d.get('zone', '')} \u00b7 {wl}\u2013{wh} W "
            f"({d.get('ftpLow')}\u2013{d.get('ftpHigh')} % FTP)\n"
            f"Struktur: {d.get('intervals', '')}\n"
            f"Fuel: {d.get('carbsPerHour') or '\u2013'} g/h \u00b7 "
            f"{d.get('fluidPerHour') or '\u2013'} ml/h \u00b7 "
            f"{(str(na) + ' mg Na/h') if na else '\u2013'}"
        )
        return summary, desc
    if t == "strength":
        ph = phases.get(_phase_for_week(week), {})
        if isinstance(d.get("exercises"), list):
            exs, label = d["exercises"], "individuell"
        else:
            exs, label = sessions.get(d.get("session", "A"), []), d.get("session", "A")
        lines = []
        for ex in exs:
            s = ex.get("sets") or ph.get("sets", "")
            r = ex.get("reps") or ph.get("reps", "")
            lines.append(f"\u2022 {ex.get('name', '')}: {s}\u00d7{r}")
        head = (
            f"RIR {ph.get('rir', '')} \u00b7 Pause {ph.get('rest', '')}\n"
            if label != "individuell"
            else ""
        )
        summary = f"\U0001F3CB Kraft {label}"
        if label != "individuell" and ph.get("label"):
            summary += f" \u00b7 {ph['label']}"
        return summary, head + "\n".join(lines)
    if t == "custom":
        return f"\u2B50 {d.get('name', 'Eigene Einheit')}", (d.get("note") or "")
    return "Ruhetag", "Erholung priorisieren."


def compute_events():
    settings = db.kv_get("settings") or {}
    plan = db.kv_get("plan") or {}
    strength = db.kv_get("strength") or {}
    log = db.kv_get("log") or {}
    weeks = plan.get("weeks") if isinstance(plan, dict) else None
    w1s = settings.get("week1Start")
    if not weeks or not w1s:
        return []
    ftp = settings.get("ftp", 283)
    phases = strength.get("phases", {})
    sessions = strength.get("sessions", {})
    w1 = _monday_of(_from_iso(w1s))
    events = []
    for wi, week in enumerate(weeks):
        for di, planday in enumerate(week):
            the_date = w1 + timedelta(days=wi * 7 + di)
            iso = the_date.strftime("%Y-%m-%d")
            entry = log.get(iso) or {}
            d = entry.get("override") or planday
            summary, desc = _render(d, wi + 1, ftp, phases, sessions)
            h = hashlib.sha1(f"{summary}|{desc}".encode("utf-8")).hexdigest()[:12]
            events.append(
                {
                    "date": iso,
                    "basic": the_date.strftime("%Y%m%d"),
                    "uid": f"cockpit-{the_date.strftime('%Y%m%d')}@trainingcockpit",
                    "summary": summary,
                    "desc": desc,
                    "hash": h,
                }
            )
    return events


def build_ics(events):
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Cockpit//Trainingsplan//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Trainingsplan Cockpit",
    ]
    for e in events:
        end = (_from_iso(e["date"]) + timedelta(days=1)).strftime("%Y%m%d")
        out += [
            "BEGIN:VEVENT",
            f"UID:{e['uid']}",
            f"DTSTAMP:{now}",
            f"DTSTART;VALUE=DATE:{e['basic']}",
            f"DTEND;VALUE=DATE:{end}",
            f"SUMMARY:{_esc(e['summary'])}",
            f"DESCRIPTION:{_esc(e['desc'])}",
            "END:VEVENT",
        ]
    out.append("END:VCALENDAR")
    return "\r\n".join(out)


def changed(events=None):
    events = events or compute_events()
    stored = db.kv_get("tp_hashes") or {}
    return [e for e in events if stored.get(e["date"]) != e["hash"]]


def mark_exported(events):
    """Record the current hash of every day, so future 'changed' exports are
    measured against this export."""
    stored = db.kv_get("tp_hashes") or {}
    for e in events:
        stored[e["date"]] = e["hash"]
    db.kv_set("tp_hashes", stored)
