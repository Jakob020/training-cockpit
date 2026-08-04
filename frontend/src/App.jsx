import { useState, useEffect, useRef } from "react";

/* ============================================================================
   TRAINING COCKPIT  ·  12-Wochen-Block (Sweet Spot → Schwelle → VO2max)
   Server-Version: Persistenz über die Backend-API (SQLite), nicht window.storage.
   Aufgebaut wie ein Renncomputer: dunkles Cockpit, Mono-Ziffern, Zonenfarben.
========================================================================== */

/* ----------------------- Storage-Layer (Backend-API) -------------------- */
const hasStore = true; // Backend übernimmt die Persistenz.

async function loadKey(key, fallback) {
  try {
    const r = await fetch(`/api/kv/${key}`);
    if (r.status === 404) return fallback;
    if (!r.ok) throw new Error("load failed");
    const j = await r.json();
    return j.value ?? fallback;
  } catch (e) { return fallback; }
}
async function saveKey(key, value) {
  try {
    const r = await fetch(`/api/kv/${key}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    });
    return r.ok;
  } catch (e) { console.error("Speichern fehlgeschlagen:", key, e); return false; }
}
async function deleteKey(key) {
  try {
    await fetch(`/api/kv/${key}`, { method: "DELETE" });
    return true;
  } catch (e) { return false; }
}
async function downloadFromApi(url, fallbackName) {
  try {
    const r = await fetch(url);
    if (!r.ok) return false;
    const blob = await r.blob();
    const cd = r.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="([^"]+)"/);
    const name = m ? m[1] : fallbackName;
    const u = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = u; a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(u); a.remove(); }, 500);
    return true;
  } catch (e) { return false; }
}

/* ------------------------------ Datum-Helfer ---------------------------- */
const WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const WD_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
const pad = (n) => String(n).padStart(2, "0");
const toISO = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const fromISO = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const midnight = (d) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; };
const daysBetween = (a, b) => Math.round((midnight(b) - midnight(a)) / 86400000);
const mondayOf = (d) => { const x = midnight(d); const wd = (x.getDay() + 6) % 7; x.setDate(x.getDate() - wd); return x; };
const wdIndex = (d) => (d.getDay() + 6) % 7;
function dayInfo(dateISO, week1ISO) {
  const d = fromISO(dateISO);
  const w1 = mondayOf(fromISO(week1ISO));
  const diff = daysBetween(w1, d);
  const week = Math.floor(diff / 7) + 1;
  return { week, wd: wdIndex(d), inPlan: week >= 1 && week <= 12 };
}
const fmtDate = (dISO) => {
  const d = fromISO(dISO);
  return `${WD_LONG[wdIndex(d)]}, ${d.getDate()}.${d.getMonth() + 1}.${d.getFullYear()}`;
};

/* ------------------------------ Zahl-Helfer ----------------------------- */
const num = (v) => { const n = Number(v); return isFinite(n) ? n : 0; };
const numOrNull = (v) => { if (v === "" || v === null || v === undefined) return null; const n = Number(v); return isFinite(n) ? n : null; };
const r5 = (n) => Math.round(n / 5) * 5;
const r50 = (n) => Math.round(n / 50) * 50;
const watt = (ftp, pct) => Math.round(ftp * num(pct) / 100);
const newId = () => Math.random().toString(36).slice(2, 8);
const de = (n) => String(n).replace(".", ",");

function zoneColor(pctHigh) {
  const p = num(pctHigh);
  if (p <= 0) return "var(--faint)";
  if (p <= 60) return "var(--z1)";
  if (p <= 76) return "var(--z2)";
  if (p <= 88) return "var(--z3)";
  if (p <= 100) return "var(--z4)";
  if (p <= 110) return "var(--z5)";
  return "var(--z6)";
}

/* ------------------------------ Defaults -------------------------------- */
function ride(name, dur, zone, ftpLow, ftpHigh, intervals, cph, fph, sph, dayType) {
  return { type: "ride", name, duration: dur, zone, ftpLow, ftpHigh, intervals, carbsPerHour: cph, fluidPerHour: fph, sodiumPerHour: sph, dayType };
}
const strengthDay = (session) => ({ type: "strength", name: "Krafttraining", session, dayType: "strength" });
const restDay = () => ({ type: "rest", name: "Ruhetag", dayType: "rest" });

const BLOCK1 = () => [
  strengthDay("A"),
  ride("Sweet Spot", 1.5, "Sweet Spot", 88, 94, "3×15 min @88–94 % FTP · 5 min RB", 78, 775, 850, "medium"),
  ride("Grundlage", 1.75, "Z2", 60, 75, "Gleichmäßig Z2", 55, 600, null, "medium"),
  strengthDay("B"),
  ride("Sweet Spot", 1.5, "Sweet Spot", 88, 94, "3×12 min @88–94 % FTP · 5 min RB", 78, 775, 850, "medium"),
  ride("Lange Grundlagenfahrt", 4, "Z2", 60, 75, "4 h Z2 + 2×10 min Tempo (~88 %)", 85, 950, 1000, "long"),
  ride("Regeneration", 1.25, "Z1", 50, 60, "Locker Z1", 20, 500, null, "recovery"),
];
const BLOCK2 = () => [
  strengthDay("A"),
  ride("Schwelle", 1.5, "Z4", 95, 105, "3×12 min @95–105 % FTP · 6 min RB", 78, 775, 850, "medium"),
  ride("Grundlage", 1.75, "Z2", 60, 75, "Gleichmäßig Z2", 55, 600, null, "medium"),
  strengthDay("B"),
  ride("Over/Unders", 1.5, "Z4/5", 88, 105, "4×(3 min @88 % / 2 min @105 %)", 78, 775, 850, "medium"),
  ride("Lange Grundlagenfahrt", 4, "Z2", 60, 75, "4 h + 3×8 min Tempo", 85, 950, 1000, "long"),
  ride("Regeneration", 1.25, "Z1", 50, 60, "Locker Z1", 20, 500, null, "recovery"),
];
const BLOCK3 = () => [
  strengthDay("A"),
  ride("VO2max", 1.25, "Z5", 106, 120, "5×4 min @106–120 % FTP · 4 min RB", 60, 700, 700, "medium"),
  ride("Grundlage", 1.75, "Z2", 60, 75, "Gleichmäßig Z2", 55, 600, null, "medium"),
  strengthDay("B"),
  ride("Schwellenerhalt", 1.25, "Z4", 95, 100, "2×15 min @95–100 % FTP", 78, 775, 850, "medium"),
  ride("Grundlage", 3.5, "Z2", 60, 75, "3,5 h + 3×10 min Tempo", 85, 950, 1000, "long"),
  ride("Regeneration", 1.25, "Z1", 50, 60, "Locker Z1", 20, 500, null, "recovery"),
];
function blockForWeek(w) { return w <= 4 ? BLOCK1() : w <= 8 ? BLOCK2() : BLOCK3(); }

function generateWeek(w) {
  let days = blockForWeek(w).map((d) => ({ ...d }));
  const deload = w === 4 || w === 8;
  const taper = w === 12;
  if (deload) {
    days = days.map((d) => {
      if (d.type !== "ride") return d;
      const nd = { ...d, duration: Math.max(0.5, Math.round(num(d.duration) * 0.6 * 4) / 4) };
      nd.name = d.name + " · Deload";
      nd.intervals = "Reduziert (Deload): " + d.intervals;
      return nd;
    });
  }
  if (taper) {
    days = days.map((d, i) => {
      if (d.type === "strength" && i === 3) {
        return ride("FTP-Test", 1, "Z4", 95, 105, "20 min all-out → neuer FTP", 60, 700, 700, "medium");
      }
      if (d.type !== "ride") return d;
      const nd = { ...d, duration: Math.max(0.5, Math.round(num(d.duration) * 0.55 * 4) / 4) };
      nd.name = d.name + " · Taper";
      nd.intervals = "Taper: " + d.intervals;
      return nd;
    });
  }
  return days.map((d, i) => ({ ...d, id: `w${w}-${i}`, weekday: WD[i] }));
}
function generatePlan() {
  return { weeks: Array.from({ length: 12 }, (_, i) => generateWeek(i + 1)) };
}

const DEFAULT_SETTINGS = {
  week1Start: toISO(mondayOf(new Date())),
  ftp: 283, startWeight: 91, targetMin: 83, targetMax: 87, height: 190,
};

const DEFAULT_NUTRITION = {
  rest: { label: "Ruhetag (inaktiv)", days: "kein Training", kcalMin: 1800, kcalMax: 1900, proteinMin: 190, proteinMax: 200, carbs: 130, fat: 60 },
  strength: { label: "Kraft-Tag", days: "Mo · Do", kcalMin: 2050, kcalMax: 2200, proteinMin: 190, proteinMax: 200, carbs: 190, fat: 60 },
  recovery: { label: "Regeneration (leichte Aktivität)", days: "So", kcalMin: 2200, kcalMax: 2350, proteinMin: 190, proteinMax: 200, carbs: 220, fat: 70 },
  medium: { label: "Mittlerer Trainingstag", days: "Di · Mi · Fr", kcalMin: 2900, kcalMax: 3100, proteinMin: 190, proteinMax: 200, carbs: 380, fat: 80 },
  long: { label: "Langer Tag", days: "Sa", kcalMin: 3800, kcalMax: 4200, proteinMin: 190, proteinMax: 200, carbs: 600, fat: 90 },
};
const DAYTYPE_ORDER = ["rest", "strength", "recovery", "medium", "long"];
const DAYTYPE_SHORT = { rest: "Ruhe", strength: "Kraft", recovery: "Regen", medium: "Mittel", long: "Lang" };

const DEFAULT_STRENGTH = {
  sessions: {
    A: [
      { id: "a0", name: "Brustpresse (Maschine)" },
      { id: "a1", name: "Latzug breit" },
      { id: "a2", name: "Schulterdrücken (Maschine)" },
      { id: "a3", name: "Rudern sitzend eng" },
      { id: "a4", name: "Bizepscurl" },
      { id: "a5", name: "Trizeps Pushdown (Cable)" },
      { id: "a6", name: "Reverse Fly (Maschine)" },
    ],
    B: [
      { id: "b0", name: "Schrägbankdrücken (KH)", note: "Start 15 kg/Hand" },
      { id: "b1", name: "Rudern vorgebeugt / T-Bar" },
      { id: "b2", name: "Seitheben" },
      { id: "b3", name: "Klimmzugmaschine (assisted)" },
      { id: "b4", name: "Hammercurl", note: "Start 7,5 kg/Hand" },
      { id: "b5", name: "Trizeps Overhead (Cable)" },
      { id: "b6", name: "Reverse Fly (Maschine)" },
    ],
  },
  phases: {
    hypertrophy: { label: "Hypertrophie", weeks: "1–3", sets: "4", reps: "8–12", rir: "2–3", rest: "90 s" },
    deload1: { label: "Deload", weeks: "4", sets: "2", reps: "10–12", rir: "3–4", rest: "90 s" },
    strength: { label: "Kraft", weeks: "5–7", sets: "4–5", reps: "5–8", rir: "1–2", rest: "2–3 min" },
    deload2: { label: "Deload", weeks: "8", sets: "2–3", reps: "8", rir: "3–4", rest: "2 min" },
    maintenance: { label: "Erhalt", weeks: "9–11", sets: "3", reps: "8–10", rir: "2", rest: "2 min" },
    taper: { label: "Taper", weeks: "12", sets: "2", reps: "10", rir: "3", rest: "2 min" },
  },
};
const PHASE_ORDER = ["hypertrophy", "deload1", "strength", "deload2", "maintenance", "taper"];
function phaseForWeek(w) {
  if (w <= 3) return "hypertrophy";
  if (w === 4) return "deload1";
  if (w <= 7) return "strength";
  if (w === 8) return "deload2";
  if (w <= 11) return "maintenance";
  return "taper";
}
const BLOCK_NAME = (w) => (w <= 4 ? "Block 1 · Sweet Spot" : w <= 8 ? "Block 2 · Schwelle" : "Block 3 · VO2max");

/* --------------------------- Datei-Export/Import ------------------------ */
function downloadFile(filename, content, mime) {
  try {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 500);
    return true;
  } catch (e) { console.error("Download fehlgeschlagen", e); return false; }
}
function buildICS(plan, strength, settings) {
  const w1 = mondayOf(fromISO(settings.week1Start));
  const esc = (s) => String(s).replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");
  const dt = (d) => `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`;
  const now = new Date();
  const stamp = `${now.getUTCFullYear()}${pad(now.getUTCMonth() + 1)}${pad(now.getUTCDate())}T${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}${pad(now.getUTCSeconds())}Z`;
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Cockpit//Trainingsplan//DE", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Trainingsplan Cockpit"];
  plan.weeks.forEach((week, wi) => {
    week.forEach((d, di) => {
      if (d.type === "rest") return;
      const date = addDays(w1, wi * 7 + di);
      const next = addDays(date, 1);
      let summary = "", desc = "";
      if (d.type === "ride") {
        const wl = watt(settings.ftp, d.ftpLow), wh = watt(settings.ftp, d.ftpHigh);
        summary = `🚴 ${d.name} · ${de(num(d.duration))} h`;
        desc = `Zone ${d.zone} · ${wl}–${wh} W (${d.ftpLow}–${d.ftpHigh} % FTP)\nStruktur: ${d.intervals}\nFuel: ${d.carbsPerHour || "–"} g/h · ${d.fluidPerHour || "–"} ml/h · ${d.sodiumPerHour ? d.sodiumPerHour + " mg Na/h" : "–"}`;
      } else {
        const ph = strength.phases[phaseForWeek(wi + 1)];
        const list = (strength.sessions[d.session] || []).map((ex) => `• ${ex.name}: ${ex.sets || ph.sets}×${ex.reps || ph.reps}`).join("\n");
        summary = `🏋 Kraft ${d.session} · ${ph.label}`;
        desc = `RIR ${ph.rir} · Pause ${ph.rest}\n${list}`;
      }
      lines.push("BEGIN:VEVENT", `UID:cockpit-w${wi + 1}-${di}@local`, `DTSTAMP:${stamp}`,
        `DTSTART;VALUE=DATE:${dt(date)}`, `DTEND;VALUE=DATE:${dt(next)}`,
        `SUMMARY:${esc(summary)}`, `DESCRIPTION:${esc(desc)}`, "END:VEVENT");
    });
  });
  lines.push("END:VCALENDAR");
  return lines.join("\r\n");
}
function parseDateToken(tok) {
  let m = tok.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (m) return `${m[1]}-${pad(+m[2])}-${pad(+m[3])}`;
  m = tok.match(/^(\d{1,2})\.(\d{1,2})\.(\d{2,4})$/);
  if (m) { let y = m[3]; if (y.length === 2) y = "20" + y; return `${y}-${pad(+m[2])}-${pad(+m[1])}`; }
  return null;
}
function parseImport(text) {
  const out = [];
  text.split(/\r?\n/).forEach((line) => {
    const t = line.trim();
    if (!t || /datum|date|kcal/i.test(t) && !/\d{4}|\d\.\d/.test(t)) return;
    const sep = /[;\t]/.test(t) ? /[;\t]+/ : /,+/;
    const tokens = t.split(sep).map((x) => x.trim()).filter(Boolean);
    let date = null; const nums = [];
    tokens.forEach((tok) => {
      const d = parseDateToken(tok);
      if (d && !date) { date = d; return; }
      const nm = tok.replace(/\s/g, "").replace(",", ".");
      if (/^\d+(\.\d+)?$/.test(nm)) nums.push(Number(nm));
    });
    if (date && nums.length >= 1) {
      out.push({
        date,
        kcal: nums[0] != null ? Math.round(nums[0]) : null,
        protein: nums[1] != null ? Math.round(nums[1]) : null,
        carbs: nums[2] != null ? Math.round(nums[2]) : null,
        fat: nums[3] != null ? Math.round(nums[3]) : null,
      });
    }
  });
  return out;
}

/* ============================== UI-Bausteine ============================= */
function Card({ children, style, accent }) {
  return <div className="trn-card" style={{ borderLeft: accent ? `3px solid ${accent}` : undefined, ...style }}>{children}</div>;
}
function Eyebrow({ children, color }) {
  return <div className="trn-eyebrow" style={{ color: color || "var(--faint)" }}>{children}</div>;
}
function Btn({ children, onClick, variant = "ghost", small, style, disabled }) {
  return (
    <button className={`trn-btn ${variant === "primary" ? "trn-btn-primary" : variant === "danger" ? "trn-btn-danger" : ""}`}
      onClick={onClick} disabled={disabled}
      style={{ ...(small ? { padding: "6px 10px", fontSize: 12 } : {}), ...style }}>{children}</button>
  );
}
function Field({ label, value, onChange, type = "text", suffix, placeholder, style }) {
  return (
    <label className="trn-field" style={style}>
      {label && <span className="trn-field-label">{label}</span>}
      <span className="trn-field-input">
        <input className="trn-input" type={type === "number" ? "text" : type}
          inputMode={type === "number" ? "decimal" : undefined}
          value={value === null || value === undefined ? "" : value}
          placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
        {suffix && <span className="trn-suffix">{suffix}</span>}
      </span>
    </label>
  );
}
function Seg({ options, value, onChange }) {
  return (
    <div className="trn-seg">
      {options.map((o) => (
        <button key={o.value} className={`trn-seg-btn ${value === o.value ? "active" : ""}`} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}
function Bar({ pct, color }) {
  return <div className="trn-bar"><div className="trn-bar-fill" style={{ width: `${Math.max(0, Math.min(100, pct))}%`, background: color || "var(--accent)" }} /></div>;
}

/* ================================ APP =================================== */
export default function App() {
  const [loading, setLoading] = useState(true);
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const [plan, setPlan] = useState(null);
  const [nutrition, setNutrition] = useState(DEFAULT_NUTRITION);
  const [strength, setStrength] = useState(DEFAULT_STRENGTH);
  const [log, setLog] = useState({});
  const [tab, setTab] = useState("today");
  const [viewISO, setViewISO] = useState(toISO(new Date()));
  const [toast, setToast] = useState(null);
  const loadedRef = useRef(false);
  const timers = useRef({});

  useEffect(() => {
    (async () => {
      const [s, p, n, st, l] = await Promise.all([
        loadKey("settings", DEFAULT_SETTINGS),
        loadKey("plan", null),
        loadKey("nutrition", DEFAULT_NUTRITION),
        loadKey("strength", DEFAULT_STRENGTH),
        loadKey("log", {}),
      ]);
      setSettings({ ...DEFAULT_SETTINGS, ...s });
      let planData = p && p.weeks ? p : generatePlan();
      planData = { weeks: planData.weeks.map((w) => w.map((d) => (d.type === "strength" && (!d.dayType || d.dayType === "rest") ? { ...d, dayType: "strength" } : d))) };
      setPlan(planData);
      setNutrition({ ...DEFAULT_NUTRITION, ...n });
      setStrength(st && st.sessions ? st : DEFAULT_STRENGTH);
      setLog(l || {});
      loadedRef.current = true;
      setLoading(false);
    })();
  }, []);

  const persist = (key, value) => {
    if (!loadedRef.current) return;
    clearTimeout(timers.current[key]);
    timers.current[key] = setTimeout(() => saveKey(key, value), 500);
  };
  useEffect(() => { persist("settings", settings); }, [settings]);
  useEffect(() => { if (plan) persist("plan", plan); }, [plan]);
  useEffect(() => { persist("nutrition", nutrition); }, [nutrition]);
  useEffect(() => { persist("strength", strength); }, [strength]);
  useEffect(() => { persist("log", log); }, [log]);

  const flash = (msg) => { setToast(msg); setTimeout(() => setToast(null), 1800); };

  if (loading) {
    return (
      <div className="trn" style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Style />
        <div style={{ textAlign: "center", color: "var(--dim)" }}>
          <div className="trn-spinner" />
          <div style={{ marginTop: 14, fontFamily: "var(--mono)", fontSize: 13, letterSpacing: 1 }}>Dashboard wird geladen…</div>
        </div>
      </div>
    );
  }

  const info = dayInfo(viewISO, settings.week1Start);
  const dayEntry = log[viewISO] || {};
  const updateLog = (dateISO, patch) => setLog((prev) => ({ ...prev, [dateISO]: { ...(prev[dateISO] || {}), ...patch } }));

  return (
    <div className="trn">
      <Style />
      <div className="trn-shell">
        <Header info={info} settings={settings} />
        <div className="trn-content">
          {!hasStore && <div className="trn-warn">Speicher nicht verfügbar — Eingaben werden in dieser Sitzung gehalten, aber nicht dauerhaft gesichert.</div>}

          {tab === "today" && (
            <TodayView info={info} viewISO={viewISO} setViewISO={setViewISO} settings={settings}
              plan={plan} nutrition={nutrition} strength={strength} entry={dayEntry} updateLog={updateLog} log={log} flash={flash} />
          )}
          {tab === "stats" && (
            <StatsView info={info} settings={settings} plan={plan} nutrition={nutrition} strength={strength} log={log} />
          )}
          {tab === "plan" && (
            <PlanView plan={plan} setPlan={setPlan} nutrition={nutrition} setNutrition={setNutrition} strength={strength} setStrength={setStrength} flash={flash} />
          )}
          {tab === "setup" && (
            <SetupView settings={settings} setSettings={setSettings} plan={plan} strength={strength} log={log}
              setPlan={setPlan} setNutrition={setNutrition} setStrength={setStrength} setLog={setLog} flash={flash} />
          )}
        </div>

        <nav className="trn-tabbar">
          {[
            { id: "today", label: "Heute", icon: "◎" },
            { id: "stats", label: "Auswertung", icon: "◧" },
            { id: "plan", label: "Plan", icon: "≡" },
            { id: "setup", label: "Setup", icon: "⚙" },
          ].map((t) => (
            <button key={t.id} className={`trn-tab ${tab === t.id ? "active" : ""}`} onClick={() => setTab(t.id)}>
              <span className="trn-tab-icon">{t.icon}</span><span>{t.label}</span>
            </button>
          ))}
        </nav>
        {toast && <div className="trn-toast">{toast}</div>}
      </div>
    </div>
  );
}

/* ------------------------------- Header --------------------------------- */
function Header({ info, settings }) {
  const phase = info.inPlan ? BLOCK_NAME(info.week) : "Außerhalb des Plans";
  return (
    <header className="trn-header">
      <div>
        <div className="trn-brand">COCKPIT</div>
        <div className="trn-header-sub">FTP {settings.ftp} W · {phase}</div>
      </div>
      <div className="trn-header-week">
        <span className="trn-header-week-num">{info.inPlan ? `W${info.week}` : "—"}</span>
        <span className="trn-header-week-lab">{info.inPlan ? `${WD[info.wd]} · Woche ${info.week}/12` : WD[info.wd]}</span>
      </div>
    </header>
  );
}

/* ============================== HEUTE =================================== */
function TodayView({ info, viewISO, setViewISO, settings, plan, nutrition, strength, entry, updateLog, log, flash }) {
  const [ovEdit, setOvEdit] = useState(false);
  const planDay = info.inPlan ? plan.weeks[info.week - 1][info.wd] : null;
  const day = entry.override || planDay;
  const isToday = viewISO === toISO(new Date());
  const phWeek = info.inPlan ? info.week : 1;

  const saveOverride = (ov) => { updateLog(viewISO, { override: ov }); setOvEdit(false); flash("Einheit für diesen Tag ersetzt"); };
  const clearOverride = () => { updateLog(viewISO, { override: null }); flash("Zurück zum Planeintrag"); };

  return (
    <div className="trn-stack">
      <div className="trn-datenav">
        <button className="trn-nav-btn" onClick={() => setViewISO(toISO(addDays(fromISO(viewISO), -1)))}>‹</button>
        <div className="trn-datenav-center">
          <div className="trn-datenav-date">{fmtDate(viewISO)}</div>
          {!isToday && <button className="trn-today-jump" onClick={() => setViewISO(toISO(new Date()))}>→ Heute</button>}
        </div>
        <button className="trn-nav-btn" onClick={() => setViewISO(toISO(addDays(fromISO(viewISO), 1)))}>›</button>
      </div>

      {entry.override && (
        <div className="trn-override-banner">
          <span>Manuell ersetzt für diesen Tag</span>
          <button onClick={clearOverride}>Zurück zum Plan</button>
        </div>
      )}

      {!day && <Card><div className="trn-empty">Kein Planeintrag für diesen Tag. Du kannst trotzdem Gewicht und Ernährung erfassen.</div></Card>}

      {day && day.type === "ride" && <RideCockpit day={day} ftp={settings.ftp} />}
      {day && day.type === "strength" && <StrengthCard day={day} week={phWeek} strength={strength} viewISO={viewISO} entry={entry} updateLog={updateLog} log={log} />}
      {day && day.type === "rest" && (
        <Card accent="var(--faint)"><Eyebrow>Heute</Eyebrow><div className="trn-ride-name">Ruhetag</div>
          <div className="trn-ride-int" style={{ marginTop: 6 }}>Erholung priorisieren — Schlaf, Protein, Flüssigkeit.</div></Card>
      )}
      {day && day.type === "custom" && (
        <Card accent="var(--accent)"><Eyebrow>Heute · Manuell</Eyebrow><div className="trn-ride-name">{day.name || "Eigene Einheit"}</div>
          {day.note && <div className="trn-ride-int" style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>{day.note}</div>}</Card>
      )}

      {!ovEdit && (
        <button className="trn-replace-btn" onClick={() => setOvEdit(true)}>
          {entry.override ? "Ersatz bearbeiten" : "Einheit für heute ersetzen"}
        </button>
      )}
      {ovEdit && (
        <OverrideEditor initial={entry.override || planDay} strength={strength}
          onSave={saveOverride} onCancel={() => setOvEdit(false)} />
      )}

      <NutritionCard day={day || { dayType: "rest" }} nutrition={nutrition} entry={entry} viewISO={viewISO} updateLog={updateLog} />

      <Card>
        <div className="trn-row-between">
          <label className="trn-check">
            <input type="checkbox" checked={!!entry.done} onChange={(e) => updateLog(viewISO, { done: e.target.checked })} />
            <span>Einheit absolviert</span>
          </label>
          <div className="trn-weight-inline">
            <span className="trn-mini-label">Gewicht morgens</span>
            <input className="trn-input trn-input-num" inputMode="decimal" placeholder="—"
              value={entry.weight ?? ""} onChange={(e) => updateLog(viewISO, { weight: e.target.value === "" ? null : e.target.value })} />
            <span className="trn-suffix">kg</span>
          </div>
        </div>
        <textarea className="trn-textarea" placeholder="Notiz (Gefühl, Wetter, RPE …)"
          value={entry.note || ""} onChange={(e) => updateLog(viewISO, { note: e.target.value })} />
      </Card>
    </div>
  );
}

function OverrideEditor({ initial, strength, onSave, onCancel }) {
  // Vorlage für eine frei zusammengestellte Krafteinheit: die geplanten
  // Übungen der Session A als Startpunkt, komplett editierbar.
  const seedStrengthExercises = () => (strength.sessions.A || []).map((e) => ({ id: newId(), name: e.name, sets: "", reps: "" }));
  const seed = initial && initial.type === "ride"
    ? { ...initial }
    : initial && initial.type === "strength"
      ? { type: "strength", name: initial.name || "Krafttraining", dayType: "strength", exercises: Array.isArray(initial.exercises) ? initial.exercises : seedStrengthExercises() }
      : initial && initial.type === "custom" ? { ...initial }
        : { type: "ride", name: "Eigene Einheit", duration: 1.5, zone: "Z2", ftpLow: 60, ftpHigh: 75, intervals: "", carbsPerHour: 60, fluidPerHour: 700, sodiumPerHour: null, dayType: "medium" };
  const [d, setD] = useState(seed);
  const set = (patch) => setD((p) => ({ ...p, ...patch }));
  const changeType = (type) => {
    if (type === "ride") setD({ type: "ride", name: "Eigene Einheit", duration: 1.5, zone: "Z2", ftpLow: 60, ftpHigh: 75, intervals: "", carbsPerHour: 60, fluidPerHour: 700, sodiumPerHour: null, dayType: "medium" });
    else if (type === "strength") setD({ type: "strength", name: "Krafttraining", dayType: "strength", exercises: seedStrengthExercises() });
    else if (type === "rest") setD({ type: "rest", name: "Ruhetag", dayType: "rest" });
    else setD({ type: "custom", name: "Eigene Einheit", note: "", dayType: "medium" });
  };
  const exUpd = (id, patch) => set({ exercises: d.exercises.map((e) => (e.id === id ? { ...e, ...patch } : e)) });
  const exDel = (id) => set({ exercises: d.exercises.filter((e) => e.id !== id) });
  const exAdd = () => set({ exercises: [...(d.exercises || []), { id: newId(), name: "", sets: "", reps: "" }] });
  return (
    <Card accent="var(--accent)">
      <Eyebrow color="var(--accent)">Einheit ersetzen (nur dieser Tag)</Eyebrow>
      <div style={{ marginTop: 10 }}>
        <Seg value={d.type} onChange={changeType}
          options={[{ value: "ride", label: "Rad" }, { value: "strength", label: "Kraft" }, { value: "custom", label: "Frei" }, { value: "rest", label: "Ruhe" }]} />
      </div>
      {d.type === "ride" && (
        <div className="trn-edit-grid">
          <Field label="Name" value={d.name} onChange={(v) => set({ name: v })} style={{ gridColumn: "1 / -1" }} />
          <Field label="Dauer" type="number" suffix="h" value={d.duration} onChange={(v) => set({ duration: v })} />
          <Field label="Zone" value={d.zone} onChange={(v) => set({ zone: v })} />
          <Field label="%FTP von" type="number" value={d.ftpLow} onChange={(v) => set({ ftpLow: v })} />
          <Field label="%FTP bis" type="number" value={d.ftpHigh} onChange={(v) => set({ ftpHigh: v })} />
          <label className="trn-field" style={{ gridColumn: "1 / -1" }}>
            <span className="trn-field-label">Intervallstruktur</span>
            <textarea className="trn-textarea sm" value={d.intervals || ""} onChange={(e) => set({ intervals: e.target.value })} />
          </label>
          <Field label="Carbs" type="number" suffix="g/h" value={d.carbsPerHour} onChange={(v) => set({ carbsPerHour: v })} />
          <Field label="Flüssigkeit" type="number" suffix="ml/h" value={d.fluidPerHour} onChange={(v) => set({ fluidPerHour: v })} />
          <Field label="Natrium" type="number" suffix="mg/h" value={d.sodiumPerHour} onChange={(v) => set({ sodiumPerHour: v === "" ? null : v })} />
        </div>
      )}
      {d.type === "strength" && (
        <div style={{ marginTop: 12 }}>
          <Field label="Name der Einheit" value={d.name} onChange={(v) => set({ name: v })} />
          <div className="trn-mini-label" style={{ margin: "12px 0 6px" }}>Übungen · Sätze × Wdh. (frei editierbar)</div>
          <div className="trn-ovr-ex-head"><span>Übung</span><span>Sätze</span><span>Wdh.</span><span /></div>
          {(d.exercises || []).map((ex) => (
            <div className="trn-ovr-ex-row" key={ex.id}>
              <input className="trn-input" placeholder="Übung" value={ex.name} onChange={(e) => exUpd(ex.id, { name: e.target.value })} />
              <input className="trn-input trn-ovr-sr" placeholder="3" value={ex.sets} onChange={(e) => exUpd(ex.id, { sets: e.target.value })} />
              <input className="trn-input trn-ovr-sr" placeholder="10" value={ex.reps} onChange={(e) => exUpd(ex.id, { reps: e.target.value })} />
              <button className="trn-del" onClick={() => exDel(ex.id)}>✕</button>
            </div>
          ))}
          <Btn small onClick={exAdd} style={{ marginTop: 8 }}>+ Übung hinzufügen</Btn>
        </div>
      )}
      {d.type === "custom" && (
        <div style={{ marginTop: 10 }}>
          <Field label="Name" value={d.name} onChange={(v) => set({ name: v })} />
          <label className="trn-field" style={{ marginTop: 10 }}><span className="trn-field-label">Beschreibung</span>
            <textarea className="trn-textarea sm" value={d.note || ""} onChange={(e) => set({ note: e.target.value })} /></label>
        </div>
      )}
      <div className="trn-mini-label" style={{ margin: "12px 0 6px" }}>Ernährungstyp für diesen Tag</div>
      <select className="trn-select" value={d.dayType} onChange={(e) => set({ dayType: e.target.value })}>
        {DAYTYPE_ORDER.map((k) => <option key={k} value={k}>{DAYTYPE_SHORT[k]}</option>)}
      </select>
      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <Btn variant="primary" onClick={() => onSave({ ...d, manual: true })}>Speichern</Btn>
        <Btn onClick={onCancel}>Abbrechen</Btn>
      </div>
    </Card>
  );
}

function RideCockpit({ day, ftp }) {
  const c = zoneColor(day.ftpHigh);
  const wLow = watt(ftp, day.ftpLow), wHigh = watt(ftp, day.ftpHigh);
  const dur = num(day.duration);
  const totCarb = r5(num(day.carbsPerHour) * dur);
  const totFluid = r50(num(day.fluidPerHour) * dur);
  const totSod = numOrNull(day.sodiumPerHour) === null ? null : r50(num(day.sodiumPerHour) * dur);
  return (
    <Card accent={c} style={{ paddingBottom: 4 }}>
      <div className="trn-row-between">
        <Eyebrow color={c}>Heute · {day.zone}</Eyebrow>
        <span className="trn-pill" style={{ color: c, borderColor: c }}>{de(dur)} h</span>
      </div>
      <div className="trn-ride-name">{day.name}</div>
      <div className="trn-readout" style={{ borderColor: c }}>
        <div className="trn-readout-main">
          <span className="trn-readout-num" style={{ color: c }}>{wLow}<span className="trn-readout-dash">–</span>{wHigh}</span>
          <span className="trn-readout-unit">W</span>
        </div>
        <div className="trn-readout-sub">Zielintervall · {day.ftpLow}–{day.ftpHigh} % FTP</div>
      </div>
      {day.intervals && <div className="trn-ride-int">{day.intervals}</div>}
      <div className="trn-gauges">
        <Gauge label="Kohlenhydrate" perHour={day.carbsPerHour ? `${day.carbsPerHour} g/h` : "—"} total={`${totCarb} g`} />
        <Gauge label="Flüssigkeit" perHour={day.fluidPerHour ? `${day.fluidPerHour} ml/h` : "—"} total={`${de((totFluid / 1000).toFixed(1))} l`} />
        <Gauge label="Natrium" perHour={numOrNull(day.sodiumPerHour) === null ? "—" : `${day.sodiumPerHour} mg/h`} total={totSod === null ? "—" : `${de((totSod / 1000).toFixed(1))} g`} />
      </div>
    </Card>
  );
}
function Gauge({ label, perHour, total }) {
  return <div className="trn-gauge"><div className="trn-gauge-label">{label}</div><div className="trn-gauge-total">{total}</div><div className="trn-gauge-rate">{perHour}</div></div>;
}

function StrengthCard({ day, week, strength, viewISO, entry, updateLog, log }) {
  const isCustom = Array.isArray(day.exercises);
  const sessionKey = day.session || "A";
  const exercises = isCustom ? day.exercises : (strength.sessions[sessionKey] || []);
  const ph = strength.phases[phaseForWeek(week)];
  const sw = entry.strength || {};
  const suggestFor = (exId) => {
    let best = null, bestDate = null;
    for (const [dd, e] of Object.entries(log)) {
      if (dd >= viewISO) continue;
      const v = e.strength && e.strength[exId];
      if (v !== undefined && v !== null && v !== "") { if (!bestDate || dd > bestDate) { bestDate = dd; best = v; } }
    }
    return best;
  };
  return (
    <Card accent="var(--violet)">
      <div className="trn-row-between">
        <Eyebrow color="var(--violet)">Heute · Kraft {isCustom ? "individuell" : sessionKey}</Eyebrow>
        <span className="trn-pill" style={{ color: "var(--violet)", borderColor: "var(--violet)" }}>{isCustom ? "eigene Einheit" : ph.label}</span>
      </div>
      <div className="trn-ride-name">{isCustom ? (day.name || "Individuelles Krafttraining") : `Oberkörper · Session ${sessionKey}`}</div>
      {!isCustom && <div className="trn-phase-line">Basis: <b>{ph.sets}</b> Sätze · <b>{ph.reps}</b> Wdh. · RIR <b>{ph.rir}</b> · Pause {ph.rest}</div>}
      <div className="trn-ex-list">
        {exercises.map((ex) => {
          const sug = suggestFor(ex.id);
          const val = sw[ex.id];
          const sets = ex.sets || (isCustom ? "–" : ph.sets);
          const reps = ex.reps || (isCustom ? "–" : ph.reps);
          const custom = isCustom || ex.sets || ex.reps;
          return (
            <div className="trn-ex-row" key={ex.id}>
              <div className="trn-ex-name">
                <span>{ex.name}</span>
                <span className="trn-ex-sr" style={custom ? { color: "var(--violet)" } : undefined}>{sets}×{reps}</span>
                {ex.note && <span className="trn-ex-note">{ex.note}</span>}
              </div>
              <div className="trn-ex-input">
                <input className="trn-input trn-input-num" inputMode="decimal" placeholder={sug != null ? String(sug) : "kg"}
                  value={val ?? ""} onChange={(e) => updateLog(viewISO, { strength: { ...sw, [ex.id]: e.target.value === "" ? null : e.target.value } })} />
                <span className="trn-suffix">kg</span>
              </div>
            </div>
          );
        })}
      </div>
      <div className="trn-hint">{isCustom ? "Frei zusammengestellte Einheit für heute. Leeres kg-Feld schlägt den zuletzt genutzten Wert vor." : "Sätze×Wdh. je Übung stammen aus der Phase — abweichende Werte (violett) setzt du im Plan → Kraft. Leeres kg-Feld schlägt den zuletzt genutzten Wert vor."}</div>
    </Card>
  );
}

function NutritionCard({ day, nutrition, entry, viewISO, updateLog }) {
  const t = nutrition[day.dayType] || nutrition.rest;
  const rows = [
    { key: "kcal", label: "kcal", target: `${t.kcalMin}–${t.kcalMax}`, val: entry.kcal, mid: (t.kcalMin + t.kcalMax) / 2 },
    { key: "protein", label: "Protein", target: `${t.proteinMin}–${t.proteinMax} g`, val: entry.protein, mid: (t.proteinMin + t.proteinMax) / 2, suf: "g" },
    { key: "carbs", label: "Carbs", target: `~${t.carbs} g`, val: entry.carbs, mid: t.carbs, suf: "g" },
    { key: "fat", label: "Fett", target: `~${t.fat} g`, val: entry.fat, mid: t.fat, suf: "g" },
  ];
  return (
    <Card>
      <div className="trn-row-between"><Eyebrow>Ernährung · {t.label}</Eyebrow><span className="trn-mini-label">aus Yazio übertragen</span></div>
      <div className="trn-nut-grid">
        {rows.map((r) => {
          const v = numOrNull(r.val);
          const pct = v != null && r.mid ? (v / r.mid) * 100 : 0;
          const col = r.key === "protein" ? (v != null && v >= t.proteinMin ? "var(--green)" : v != null && v >= t.proteinMin * 0.9 ? "var(--amber)" : "var(--z2)") : "var(--z2)";
          return (
            <div className="trn-nut-cell" key={r.key}>
              <div className="trn-nut-top"><span className="trn-nut-label">{r.label}</span><span className="trn-nut-target">Ziel {r.target}</span></div>
              <div className="trn-nut-inputrow">
                <input className="trn-input trn-input-num wide" inputMode="decimal" placeholder="—"
                  value={r.val ?? ""} onChange={(e) => updateLog(viewISO, { [r.key]: e.target.value === "" ? null : e.target.value })} />
                {r.suf && <span className="trn-suffix">{r.suf}</span>}
              </div>
              <Bar pct={pct} color={col} />
            </div>
          );
        })}
      </div>
    </Card>
  );
}

/* ============================ AUSWERTUNG ================================ */
function StatsView({ info, settings, plan, nutrition, strength, log }) {
  const today = new Date();
  const series = [];
  for (let i = 34; i >= 0; i--) { const dISO = toISO(addDays(today, -i)); series.push({ dISO, w: numOrNull(log[dISO]?.weight) }); }
  const withW = series.filter((p) => p.w != null);
  const avg = (arr) => (arr.length ? arr.reduce((s, x) => s + x, 0) / arr.length : null);
  const avg7 = avg(withW.slice(-7).map((p) => p.w));
  const avgPrev = avg(withW.slice(-14, -7).map((p) => p.w));
  const weeklyRate = avg7 != null && avgPrev != null ? avgPrev - avg7 : null;
  const latest = withW.length ? withW[withW.length - 1].w : null;
  const bmi = avg7 != null ? avg7 / Math.pow(settings.height / 100, 2) : null;

  let ampel = { color: "var(--faint)", label: "zu wenig Daten" };
  if (weeklyRate != null) {
    if (weeklyRate >= 0.8) ampel = { color: "var(--red)", label: "zu schnell" };
    else if (weeklyRate >= 0.6) ampel = { color: "var(--amber)", label: "leicht über Ziel" };
    else if (weeklyRate >= 0.4) ampel = { color: "var(--green)", label: "im Zielkorridor" };
    else if (weeklyRate > 0) ampel = { color: "var(--amber)", label: "zu langsam" };
    else ampel = { color: "var(--red)", label: "kein Defizit" };
  }

  const start = num(settings.startWeight), goalHi = num(settings.targetMax);
  const cur = avg7 ?? latest ?? start;
  const progPct = start > goalHi ? Math.min(100, Math.max(0, ((start - cur) / (start - goalHi)) * 100)) : 0;

  const wk = info.inPlan ? info.week : null;
  let planned = 0, done = 0, hPlan = 0, hDone = 0, strPlan = 0, strDone = 0;
  if (wk) {
    const w1mon = mondayOf(fromISO(settings.week1Start));
    const weekStart = addDays(w1mon, (wk - 1) * 7);
    plan.weeks[wk - 1].forEach((d0, i) => {
      const dISO = toISO(addDays(weekStart, i));
      const e = log[dISO] || {};
      const d = e.override || d0;
      if (d.type === "ride") { planned++; hPlan += num(d.duration); if (e.done) { done++; hDone += num(d.duration); } }
      if (d.type === "strength") { strPlan++; if (e.done) strDone++; }
    });
  }

  // Makro-Bilanz letzte 7 Tage
  const targetFor = (dISO) => {
    const inf = dayInfo(dISO, settings.week1Start);
    const ov = log[dISO]?.override;
    let dt = "rest";
    if (ov) dt = ov.dayType || "rest";
    else if (inf.inPlan) dt = plan.weeks[inf.week - 1][inf.wd].dayType || "rest";
    return nutrition[dt] || nutrition.rest;
  };
  const status = (key, v, t) => {
    if (v == null) return "none";
    if (key === "kcal") { if (v >= t.kcalMin && v <= t.kcalMax) return "hit"; if (v >= t.kcalMin * 0.88 && v <= t.kcalMax * 1.12) return "near"; return "miss"; }
    if (key === "protein") { if (v >= t.proteinMin) return "hit"; if (v >= t.proteinMin * 0.9) return "near"; return "miss"; }
    const tgt = key === "carbs" ? t.carbs : t.fat;
    const dev = Math.abs(v - tgt) / tgt;
    if (dev <= 0.15) return "hit"; if (dev <= 0.3) return "near"; return "miss";
  };
  const days7 = [];
  for (let i = 6; i >= 0; i--) {
    const dISO = toISO(addDays(today, -i));
    const e = log[dISO] || {};
    days7.push({ dISO, wd: WD[wdIndex(fromISO(dISO))], t: targetFor(dISO), e });
  }
  const macros = [
    { key: "kcal", label: "kcal" },
    { key: "protein", label: "Protein" },
    { key: "carbs", label: "Carbs" },
    { key: "fat", label: "Fett" },
  ];
  const statusColor = { hit: "var(--green)", near: "var(--amber)", miss: "var(--red)", none: "var(--border2)" };

  return (
    <div className="trn-stack">
      <Card accent={ampel.color}>
        <div className="trn-row-between"><Eyebrow>7-Tage-Gewichtstrend</Eyebrow><span className="trn-status-dot" style={{ background: ampel.color }} /></div>
        <div className="trn-trend-main">
          <div>
            <div className="trn-trend-num">{avg7 != null ? de(avg7.toFixed(1)) : "—"}<span className="trn-trend-unit">kg</span></div>
            <div className="trn-mini-label">gleitender Ø{latest != null ? ` · zuletzt ${de(latest)} kg` : ""}</div>
          </div>
          <div className="trn-trend-rate" style={{ color: ampel.color }}>
            <div className="trn-trend-rate-num">{weeklyRate != null ? `${weeklyRate > 0 ? "−" : "+"}${de(Math.abs(weeklyRate).toFixed(2))}` : "—"}</div>
            <div className="trn-mini-label" style={{ color: ampel.color }}>kg/Woche · {ampel.label}</div>
          </div>
        </div>
        <Spark series={series} min={settings.targetMin} max={settings.targetMax} />
        {bmi != null && <div className="trn-hint">BMI {de(bmi.toFixed(1))} · Zielkorridor Verlust 0,4–0,6 kg/Woche</div>}
      </Card>

      <Card>
        <Eyebrow>Fortschritt zum Zielgewicht</Eyebrow>
        <div className="trn-goal-row">
          <span className="trn-mono-sm">{de(start)} kg</span>
          <div style={{ flex: 1, margin: "0 10px" }}><Bar pct={progPct} color="var(--accent)" /></div>
          <span className="trn-mono-sm">{settings.targetMin}–{settings.targetMax}</span>
        </div>
        <div className="trn-goal-cur">Aktuell <b>{cur != null ? de(cur.toFixed(1)) : "—"} kg</b> · noch {cur != null ? de(Math.max(0, cur - goalHi).toFixed(1)) : "—"} kg bis in den Korridor</div>
      </Card>

      <Card>
        <Eyebrow>Wochenübersicht {wk ? `· Woche ${wk}` : ""}</Eyebrow>
        {wk ? (
          <div className="trn-week-stats">
            <WStat label="Radeinheiten" value={`${done}/${planned}`} />
            <WStat label="Radstunden" value={`${de(hDone.toFixed(1))}/${de(hPlan.toFixed(1))} h`} />
            <WStat label="Kraft" value={`${strDone}/${strPlan}`} />
          </div>
        ) : <div className="trn-empty">Heutiger Tag liegt außerhalb des Plans.</div>}
      </Card>

      {/* Makro-Bilanz */}
      <Card>
        <div className="trn-row-between"><Eyebrow>Makro-Bilanz · letzte 7 Tage</Eyebrow></div>
        <div className="trn-macro-grid">
          <div className="trn-macro-head">
            <span className="trn-macro-rowlabel" />
            {days7.map((d) => <span className="trn-macro-wd" key={d.dISO}>{d.wd}</span>)}
            <span className="trn-macro-avg-h">Ø</span>
          </div>
          {macros.map((m) => {
            const vals = days7.map((d) => numOrNull(d.e[m.key]));
            const present = vals.filter((v) => v != null);
            const av = present.length ? Math.round(present.reduce((s, x) => s + x, 0) / present.length) : null;
            return (
              <div className="trn-macro-row" key={m.key}>
                <span className="trn-macro-rowlabel">{m.label}</span>
                {days7.map((d, i) => {
                  const v = vals[i];
                  const st = status(m.key, v, d.t);
                  return (
                    <span className="trn-macro-cell" key={d.dISO} style={{ background: st === "none" ? "var(--surface2)" : statusColor[st] + "26", borderColor: statusColor[st] }}>
                      {v != null ? v : "·"}
                    </span>
                  );
                })}
                <span className="trn-macro-avg">{av != null ? av : "—"}</span>
              </div>
            );
          })}
        </div>
        <div className="trn-macro-legend">
          <span><i style={{ background: "var(--green)" }} />im Ziel</span>
          <span><i style={{ background: "var(--amber)" }} />knapp daneben</span>
          <span><i style={{ background: "var(--red)" }} />verfehlt</span>
        </div>
      </Card>

      <StrengthProgress plan={plan} strength={strength} settings={settings} log={log} />
    </div>
  );
}
function WStat({ label, value }) {
  return <div className="trn-wstat"><div className="trn-wstat-val">{value}</div><div className="trn-wstat-lab">{label}</div></div>;
}
function Spark({ series, min, max }) {
  const withW = series.map((p, i) => ({ x: i, w: p.w })).filter((p) => p.w != null);
  if (withW.length < 2) return <div className="trn-spark-empty">Trage an mehreren Tagen dein Gewicht ein, um den Verlauf zu sehen.</div>;
  const ws = withW.map((p) => p.w);
  const lo = Math.min(...ws, min) - 0.5, hi = Math.max(...ws, max) + 0.5;
  const W = 320, H = 70;
  const X = (i) => (i / (series.length - 1)) * W;
  const Y = (w) => H - ((w - lo) / (hi - lo)) * H;
  const d = withW.map((p, i) => `${i === 0 ? "M" : "L"}${X(p.x).toFixed(1)},${Y(p.w).toFixed(1)}`).join(" ");
  const bandTop = Y(max), bandBot = Y(min);
  return (
    <svg className="trn-spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <rect x="0" y={bandTop} width={W} height={Math.max(1, bandBot - bandTop)} fill="var(--green)" opacity="0.12" />
      <line x1="0" y1={bandTop} x2={W} y2={bandTop} stroke="var(--green)" strokeWidth="0.8" opacity="0.5" strokeDasharray="3 3" />
      <line x1="0" y1={bandBot} x2={W} y2={bandBot} stroke="var(--green)" strokeWidth="0.8" opacity="0.5" strokeDasharray="3 3" />
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      {withW.map((p, i) => <circle key={i} cx={X(p.x)} cy={Y(p.w)} r="2" fill="var(--accent)" />)}
    </svg>
  );
}
function StrengthProgress({ plan, strength, settings, log }) {
  const allEx = [...strength.sessions.A.map((e) => ({ ...e, session: "A" })), ...strength.sessions.B.map((e) => ({ ...e, session: "B" }))];
  const [exId, setExId] = useState(allEx[0]?.id);
  const ex = allEx.find((e) => e.id === exId) || allEx[0];
  if (!ex) return null;
  const w1mon = mondayOf(fromISO(settings.week1Start));
  const rows = [];
  for (let wk = 1; wk <= 12; wk++) {
    const idx = plan.weeks[wk - 1].findIndex((d) => d.type === "strength" && (d.session || "A") === ex.session);
    if (idx < 0) continue;
    const dISO = toISO(addDays(w1mon, (wk - 1) * 7 + idx));
    const v = log[dISO]?.strength?.[ex.id];
    if (v != null && v !== "") rows.push({ wk, v: num(v) });
  }
  const maxV = rows.length ? Math.max(...rows.map((r) => r.v)) : 0;
  return (
    <Card>
      <Eyebrow>Kraft-Verlauf</Eyebrow>
      <select className="trn-select" value={exId} onChange={(e) => setExId(e.target.value)}>
        {allEx.map((e) => <option key={e.id} value={e.id}>{e.session} · {e.name}</option>)}
      </select>
      {rows.length === 0 ? <div className="trn-empty" style={{ marginTop: 10 }}>Noch keine Gewichte für diese Übung eingetragen.</div> : (
        <div className="trn-strhist">
          {rows.map((r) => (
            <div className="trn-strhist-row" key={r.wk}>
              <span className="trn-strhist-wk">W{r.wk}</span>
              <div className="trn-strhist-bar"><div style={{ width: `${(r.v / maxV) * 100}%` }} /></div>
              <span className="trn-strhist-val">{de(r.v)} kg</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

/* ============================== PLAN ==================================== */
function PlanView({ plan, setPlan, nutrition, setNutrition, strength, setStrength, flash }) {
  const [section, setSection] = useState("rides");
  return (
    <div className="trn-stack">
      <Seg value={section} onChange={setSection} options={[{ value: "rides", label: "Radplan" }, { value: "strength", label: "Kraft" }, { value: "nutrition", label: "Ernährung" }]} />
      {section === "rides" && <RidePlanEditor plan={plan} setPlan={setPlan} flash={flash} />}
      {section === "strength" && <StrengthEditor strength={strength} setStrength={setStrength} flash={flash} />}
      {section === "nutrition" && <NutritionEditor nutrition={nutrition} setNutrition={setNutrition} flash={flash} />}
    </div>
  );
}

function RidePlanEditor({ plan, setPlan, flash }) {
  const [wk, setWk] = useState(1);
  const [openId, setOpenId] = useState(null);
  const [dupTarget, setDupTarget] = useState("");
  const week = plan.weeks[wk - 1];
  const updateDay = (idx, patch) => setPlan((prev) => { const weeks = prev.weeks.map((w) => w.slice()); weeks[wk - 1] = weeks[wk - 1].map((d, i) => (i === idx ? { ...d, ...patch } : d)); return { weeks }; });
  const setDayType = (idx, type) => {
    let base;
    if (type === "rest") base = { ...restDay(), id: `w${wk}-${idx}`, weekday: WD[idx] };
    else if (type === "strength") base = { ...strengthDay(idx >= 3 ? "B" : "A"), id: `w${wk}-${idx}`, weekday: WD[idx] };
    else base = { ...ride("Neue Einheit", 1, "Z2", 60, 75, "Struktur …", 55, 600, null, "medium"), id: `w${wk}-${idx}`, weekday: WD[idx] };
    setPlan((prev) => { const weeks = prev.weeks.map((w) => w.slice()); weeks[wk - 1] = weeks[wk - 1].map((d, i) => (i === idx ? base : d)); return { weeks }; });
  };
  const resetDay = (idx) => { setPlan((prev) => { const weeks = prev.weeks.map((w) => w.slice()); weeks[wk - 1] = weeks[wk - 1].map((d, i) => (i === idx ? generateWeek(wk)[idx] : d)); return { weeks }; }); flash("Tag zurückgesetzt"); };
  const swapDay = (idx, tI) => {
    if (tI === idx) return;
    setPlan((prev) => {
      const weeks = prev.weeks.map((w) => w.slice()); const arr = weeks[wk - 1];
      const a = { ...arr[idx] }, b = { ...arr[tI] };
      a.id = `w${wk}-${tI}`; a.weekday = WD[tI]; b.id = `w${wk}-${idx}`; b.weekday = WD[idx];
      arr[idx] = b; arr[tI] = a; weeks[wk - 1] = arr; return { weeks };
    });
    flash("Getauscht");
  };
  const resetWeek = () => { setPlan((prev) => { const weeks = prev.weeks.slice(); weeks[wk - 1] = generateWeek(wk); return { weeks }; }); flash(`Woche ${wk} zurückgesetzt`); };
  const duplicateWeek = () => {
    const t = Number(dupTarget); if (!t || t === wk) return;
    setPlan((prev) => { const weeks = prev.weeks.slice(); weeks[t - 1] = plan.weeks[wk - 1].map((d, i) => ({ ...d, id: `w${t}-${i}`, weekday: WD[i] })); return { weeks }; });
    flash(`Woche ${wk} → Woche ${t} kopiert`); setDupTarget("");
  };
  return (
    <>
      <Card>
        <div className="trn-weeksel">
          <button className="trn-nav-btn" onClick={() => setWk(Math.max(1, wk - 1))}>‹</button>
          <div className="trn-weeksel-mid"><div className="trn-weeksel-num">Woche {wk}</div><div className="trn-mini-label">{BLOCK_NAME(wk)}{wk === 4 || wk === 8 ? " · Deload" : wk === 12 ? " · Taper" : ""}</div></div>
          <button className="trn-nav-btn" onClick={() => setWk(Math.min(12, wk + 1))}>›</button>
        </div>
        <div className="trn-weekdots">{Array.from({ length: 12 }, (_, i) => <button key={i} className={`trn-weekdot ${wk === i + 1 ? "active" : ""}`} onClick={() => setWk(i + 1)}>{i + 1}</button>)}</div>
      </Card>

      {week.map((d, idx) => (
        <Card key={d.id} accent={d.type === "ride" ? zoneColor(d.ftpHigh) : d.type === "strength" ? "var(--violet)" : "var(--faint)"} style={{ padding: 0 }}>
          <button className="trn-day-head" onClick={() => setOpenId(openId === d.id ? null : d.id)}>
            <span className="trn-day-wd">{WD[idx]}</span>
            <span className="trn-day-name">{d.name}{d.type === "ride" ? ` · ${de(num(d.duration))} h` : d.type === "strength" ? ` · ${d.session}` : ""}</span>
            <span className="trn-day-chev">{openId === d.id ? "▾" : "▸"}</span>
          </button>
          {openId === d.id && (
            <div className="trn-day-body">
              <div className="trn-mini-label" style={{ marginBottom: 6 }}>Art des Tages</div>
              <Seg value={d.type} onChange={(t) => setDayType(idx, t)} options={[{ value: "ride", label: "Rad" }, { value: "strength", label: "Kraft" }, { value: "rest", label: "Ruhetag" }]} />
              {d.type === "ride" && (
                <div className="trn-edit-grid">
                  <Field label="Name" value={d.name} onChange={(v) => updateDay(idx, { name: v })} style={{ gridColumn: "1 / -1" }} />
                  <Field label="Dauer" type="number" suffix="h" value={d.duration} onChange={(v) => updateDay(idx, { duration: v })} />
                  <Field label="Zone" value={d.zone} onChange={(v) => updateDay(idx, { zone: v })} />
                  <Field label="%FTP von" type="number" value={d.ftpLow} onChange={(v) => updateDay(idx, { ftpLow: v })} />
                  <Field label="%FTP bis" type="number" value={d.ftpHigh} onChange={(v) => updateDay(idx, { ftpHigh: v })} />
                  <label className="trn-field" style={{ gridColumn: "1 / -1" }}><span className="trn-field-label">Intervallstruktur</span>
                    <textarea className="trn-textarea sm" value={d.intervals} onChange={(e) => updateDay(idx, { intervals: e.target.value })} /></label>
                  <Field label="Carbs" type="number" suffix="g/h" value={d.carbsPerHour} onChange={(v) => updateDay(idx, { carbsPerHour: v })} />
                  <Field label="Flüssigkeit" type="number" suffix="ml/h" value={d.fluidPerHour} onChange={(v) => updateDay(idx, { fluidPerHour: v })} />
                  <Field label="Natrium" type="number" suffix="mg/h" value={d.sodiumPerHour} onChange={(v) => updateDay(idx, { sodiumPerHour: v === "" ? null : v })} />
                </div>
              )}
              {d.type === "strength" && (
                <div className="trn-edit-grid" style={{ marginTop: 10 }}>
                  <label className="trn-field"><span className="trn-field-label">Session</span>
                    <select className="trn-select" value={d.session} onChange={(e) => updateDay(idx, { session: e.target.value })}><option value="A">A</option><option value="B">B</option></select></label>
                </div>
              )}
              <div className="trn-mini-label" style={{ margin: "12px 0 6px" }}>Ernährungstyp (Kalorienziel)</div>
              <select className="trn-select" style={{ marginTop: 0 }} value={d.dayType} onChange={(e) => updateDay(idx, { dayType: e.target.value })}>
                {DAYTYPE_ORDER.map((k) => <option key={k} value={k}>{DAYTYPE_SHORT[k]}</option>)}
              </select>
              <div className="trn-day-actions">
                <label className="trn-move"><span>Tauschen mit</span>
                  <select className="trn-select sm" value="" onChange={(e) => e.target.value !== "" && swapDay(idx, Number(e.target.value))}>
                    <option value="">Tag wählen…</option>
                    {WD.map((w, i) => i !== idx && <option key={i} value={i}>{w}</option>)}
                  </select>
                </label>
                <Btn small onClick={() => resetDay(idx)}>Tag zurücksetzen</Btn>
              </div>
            </div>
          )}
        </Card>
      ))}

      <Card>
        <Eyebrow>Wochen-Aktionen</Eyebrow>
        <div className="trn-week-actions">
          <div className="trn-dup">
            <select className="trn-select sm" value={dupTarget} onChange={(e) => setDupTarget(e.target.value)}>
              <option value="">Kopieren nach…</option>
              {Array.from({ length: 12 }, (_, i) => i + 1).filter((n) => n !== wk).map((n) => <option key={n} value={n}>Woche {n}</option>)}
            </select>
            <Btn small variant="primary" onClick={duplicateWeek} disabled={!dupTarget}>Kopieren</Btn>
          </div>
          <Btn small variant="danger" onClick={resetWeek}>Woche auf Standard</Btn>
        </div>
      </Card>
    </>
  );
}

function StrengthEditor({ strength, setStrength, flash }) {
  const [sess, setSess] = useState("A");
  const list = strength.sessions[sess];
  const updateEx = (id, patch) => setStrength((p) => ({ ...p, sessions: { ...p.sessions, [sess]: p.sessions[sess].map((e) => (e.id === id ? { ...e, ...patch } : e)) } }));
  const delEx = (id) => setStrength((p) => ({ ...p, sessions: { ...p.sessions, [sess]: p.sessions[sess].filter((e) => e.id !== id) } }));
  const addEx = () => setStrength((p) => ({ ...p, sessions: { ...p.sessions, [sess]: [...p.sessions[sess], { id: newId(), name: "Neue Übung" }] } }));
  const move = (id, dir) => setStrength((p) => {
    const arr = p.sessions[sess].slice(); const i = arr.findIndex((e) => e.id === id); const j = i + dir;
    if (j < 0 || j >= arr.length) return p; [arr[i], arr[j]] = [arr[j], arr[i]];
    return { ...p, sessions: { ...p.sessions, [sess]: arr } };
  });
  const updatePhase = (key, patch) => setStrength((p) => ({ ...p, phases: { ...p.phases, [key]: { ...p.phases[key], ...patch } } }));
  const resetAll = () => { setStrength(DEFAULT_STRENGTH); flash("Kraftplan zurückgesetzt"); };
  return (
    <>
      <Card>
        <Seg value={sess} onChange={setSess} options={[{ value: "A", label: "Session A" }, { value: "B", label: "Session B" }]} />
        <div className="trn-ex-edit-list">
          {list.map((ex, i) => (
            <div className="trn-ex-edit" key={ex.id}>
              <div className="trn-ex-edit-main">
                <div className="trn-ex-move">
                  <button onClick={() => move(ex.id, -1)} disabled={i === 0}>▲</button>
                  <button onClick={() => move(ex.id, 1)} disabled={i === list.length - 1}>▼</button>
                </div>
                <input className="trn-input" value={ex.name} onChange={(e) => updateEx(ex.id, { name: e.target.value })} />
                <button className="trn-del" onClick={() => delEx(ex.id)}>✕</button>
              </div>
              <div className="trn-ex-edit-sr">
                <span className="trn-sr-lab">individuell</span>
                <input className="trn-input trn-sr-inp" placeholder="Sätze" value={ex.sets || ""} onChange={(e) => updateEx(ex.id, { sets: e.target.value })} />
                <span className="trn-sr-x">×</span>
                <input className="trn-input trn-sr-inp" placeholder="Wdh." value={ex.reps || ""} onChange={(e) => updateEx(ex.id, { reps: e.target.value })} />
                <span className="trn-sr-hint">leer = Phasenwert</span>
              </div>
            </div>
          ))}
        </div>
        <Btn small onClick={addEx} style={{ marginTop: 8 }}>+ Übung hinzufügen</Btn>
      </Card>

      <Card>
        <Eyebrow>Phasen · Sätze / Wdh. / RIR / Pause</Eyebrow>
        <div className="trn-hint" style={{ marginTop: 4, marginBottom: 4 }}>Standardwerte je Phase. Einzelne Übungen können oben abweichen.</div>
        <div className="trn-phase-edit">
          {PHASE_ORDER.map((k) => {
            const ph = strength.phases[k];
            return (
              <div className="trn-phase-block" key={k}>
                <div className="trn-phase-title">{ph.label} <span className="trn-mini-label">· W {ph.weeks}</span></div>
                <div className="trn-phase-fields">
                  <Field label="Sätze" value={ph.sets} onChange={(v) => updatePhase(k, { sets: v })} />
                  <Field label="Wdh." value={ph.reps} onChange={(v) => updatePhase(k, { reps: v })} />
                  <Field label="RIR" value={ph.rir} onChange={(v) => updatePhase(k, { rir: v })} />
                  <Field label="Pause" value={ph.rest} onChange={(v) => updatePhase(k, { rest: v })} />
                </div>
              </div>
            );
          })}
        </div>
        <Btn small variant="danger" onClick={resetAll} style={{ marginTop: 12 }}>Kraftplan auf Standard</Btn>
      </Card>
    </>
  );
}

function NutritionEditor({ nutrition, setNutrition, flash }) {
  const upd = (k, patch) => setNutrition((p) => ({ ...p, [k]: { ...p[k], ...patch } }));
  const reset = () => { setNutrition(DEFAULT_NUTRITION); flash("Ernährungsziele zurückgesetzt"); };
  return (
    <>
      {DAYTYPE_ORDER.map((k) => {
        const t = nutrition[k];
        return (
          <Card key={k}>
            <div className="trn-row-between"><Eyebrow>{t.label}</Eyebrow><span className="trn-mini-label">{t.days}</span></div>
            <div className="trn-edit-grid">
              <Field label="kcal von" type="number" value={t.kcalMin} onChange={(v) => upd(k, { kcalMin: num(v) })} />
              <Field label="kcal bis" type="number" value={t.kcalMax} onChange={(v) => upd(k, { kcalMax: num(v) })} />
              <Field label="Protein von" type="number" suffix="g" value={t.proteinMin} onChange={(v) => upd(k, { proteinMin: num(v) })} />
              <Field label="Protein bis" type="number" suffix="g" value={t.proteinMax} onChange={(v) => upd(k, { proteinMax: num(v) })} />
              <Field label="Carbs" type="number" suffix="g" value={t.carbs} onChange={(v) => upd(k, { carbs: num(v) })} />
              <Field label="Fett" type="number" suffix="g" value={t.fat} onChange={(v) => upd(k, { fat: num(v) })} />
            </div>
          </Card>
        );
      })}
      <Btn small variant="danger" onClick={reset}>Ernährungsziele auf Standard</Btn>
    </>
  );
}

/* ============================== SETUP ================================== */
function SetupView({ settings, setSettings, plan, strength, log, setPlan, setNutrition, setStrength, setLog, flash }) {
  const upd = (patch) => setSettings((s) => ({ ...s, ...patch }));
  const [confirmReset, setConfirmReset] = useState(false);
  const [importText, setImportText] = useState("");
  const [preview, setPreview] = useState(null);
  const [tpChanged, setTpChanged] = useState(null);
  const [yzStatus, setYzStatus] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const mon = mondayOf(fromISO(settings.week1Start));

  const refreshMeta = async () => {
    try { const r = await fetch("/api/tp/changed-count"); if (r.ok) setTpChanged((await r.json()).count); } catch (e) {}
    setYzStatus(await loadKey("yazio_status", null));
  };
  useEffect(() => { refreshMeta(); }, []);

  const onDate = (v) => { if (!v) return; upd({ week1Start: toISO(mondayOf(fromISO(v))) }); };
  const resetAll = async () => {
    await Promise.all([deleteKey("settings"), deleteKey("plan"), deleteKey("nutrition"), deleteKey("strength"), deleteKey("log")]);
    setSettings(DEFAULT_SETTINGS); setPlan(generatePlan()); setNutrition(DEFAULT_NUTRITION); setStrength(DEFAULT_STRENGTH); setLog({});
    setConfirmReset(false); flash("Alle Daten gelöscht");
  };
  const exportTP = async (scope) => {
    const ok = await downloadFromApi(`/api/tp/ics?scope=${scope}`, `trainingsplan_${scope}.ics`);
    flash(ok ? (scope === "all" ? "Alle Tage exportiert" : "Geänderte Tage exportiert") : "Export fehlgeschlagen");
    refreshMeta();
  };
  const syncYazio = async () => {
    setSyncing(true);
    try {
      const r = await fetch("/api/yazio/sync", { method: "POST" });
      const j = await r.json();
      if (j.ok) { const l = await loadKey("log", {}); setLog(l); flash(`Yazio: ${j.updated} Tage aktualisiert`); }
      else flash("Yazio-Sync fehlgeschlagen");
    } catch (e) { flash("Yazio-Sync fehlgeschlagen"); }
    setSyncing(false);
    refreshMeta();
  };
  const runPreview = () => { const p = parseImport(importText); setPreview(p); if (!p.length) flash("Keine Zeilen erkannt"); };
  const applyImport = () => {
    if (!preview || !preview.length) return;
    setLog((prev) => {
      const next = { ...prev };
      preview.forEach((r) => {
        const cur = { ...(next[r.date] || {}) };
        if (r.kcal != null) cur.kcal = r.kcal;
        if (r.protein != null) cur.protein = r.protein;
        if (r.carbs != null) cur.carbs = r.carbs;
        if (r.fat != null) cur.fat = r.fat;
        next[r.date] = cur;
      });
      return next;
    });
    flash(`${preview.length} Tage importiert`); setPreview(null); setImportText("");
  };

  return (
    <div className="trn-stack">
      <Card>
        <Eyebrow>Plan-Start</Eyebrow>
        <label className="trn-field"><span className="trn-field-label">Montag von Woche 1</span>
          <input className="trn-input" type="date" value={toISO(mon)} onChange={(e) => onDate(e.target.value)} /></label>
        <div className="trn-hint">Wird automatisch auf den Montag gesetzt. Ende Woche 12: {toISO(addDays(mon, 83))}.</div>
      </Card>

      <Card>
        <Eyebrow>Leistung & Gewicht</Eyebrow>
        <div className="trn-edit-grid">
          <Field label="FTP" type="number" suffix="W" value={settings.ftp} onChange={(v) => upd({ ftp: num(v) })} />
          <Field label="Größe" type="number" suffix="cm" value={settings.height} onChange={(v) => upd({ height: num(v) })} />
          <Field label="Startgewicht" type="number" suffix="kg" value={settings.startWeight} onChange={(v) => upd({ startWeight: num(v) })} />
          <div />
          <Field label="Zielgewicht von" type="number" suffix="kg" value={settings.targetMin} onChange={(v) => upd({ targetMin: num(v) })} />
          <Field label="Zielgewicht bis" type="number" suffix="kg" value={settings.targetMax} onChange={(v) => upd({ targetMax: num(v) })} />
        </div>
        <div className="trn-hint">Alle Watt-Ziele leiten sich live aus der FTP ab ({settings.ftp} W → Sweet Spot {watt(settings.ftp, 88)}–{watt(settings.ftp, 94)} W).</div>
      </Card>

      {/* TrainingPeaks-Export */}
      <Card accent="var(--accent)">
        <Eyebrow color="var(--accent)">TrainingPeaks / Kalender (.ics)</Eyebrow>
        <div className="trn-hint" style={{ marginTop: 4 }}>
          Jeder Tag ist ein Event mit fester Kennung (UID). Beim Re-Import in TrainingPeaks werden genau diese Tage überschrieben, alle anderen bleiben unberührt. Für kleine, auch nachträgliche Änderungen exportierst du nur die geänderten Tage.
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <Btn variant="primary" onClick={() => exportTP("changed")}>
            Nur geänderte Tage{tpChanged != null ? ` (${tpChanged})` : ""}
          </Btn>
          <Btn onClick={() => exportTP("all")}>Alle Tage</Btn>
        </div>
        <div className="trn-hint">Import in TrainingPeaks: Kalender → Datei importieren. Radeinheiten enthalten Watt-Ziele, Intervalle und Zone, Krafteinheiten die Übungen mit Sätzen×Wdh.</div>
      </Card>

      {/* Yazio-Sync */}
      <Card accent="var(--green)">
        <Eyebrow color="var(--green)">Yazio-Sync</Eyebrow>
        <div className="trn-hint" style={{ marginTop: 4 }}>
          Der Server holt deine Tageswerte automatisch einmal täglich am Tagesende (inoffizielle Yazio-API, Zugangsdaten in der .env). Du kannst jederzeit manuell synchronisieren.
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center", flexWrap: "wrap" }}>
          <Btn variant="primary" onClick={syncYazio} disabled={syncing}>{syncing ? "Synchronisiere…" : "Jetzt von Yazio synchronisieren"}</Btn>
          {yzStatus && yzStatus.lastSync && (
            <span className="trn-mini-label">
              zuletzt {yzStatus.lastSync.replace("T", " ")} · {yzStatus.ok === false ? "Fehler" : `${yzStatus.updated ?? 0} Tage`}
            </span>
          )}
        </div>
        {yzStatus && yzStatus.ok === false && <div className="trn-warn" style={{ marginTop: 10 }}>Letzter Sync-Fehler: {yzStatus.error}</div>}
        <div className="trn-hint" style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
          Fallback: Werte manuell einfügen (überschreibt die betroffenen Tage). Format je Zeile mit Semikolon: <b>Datum ; kcal ; Protein ; Carbs ; Fett</b>
        </div>
        <textarea className="trn-textarea" style={{ minHeight: 90, fontFamily: "var(--mono)", fontSize: 12 }}
          placeholder={"2026-08-04 ; 2480 ; 196 ; 320 ; 74\n2026-08-05 ; 1950 ; 198 ; 150 ; 62"}
          value={importText} onChange={(e) => setImportText(e.target.value)} />
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <Btn small onClick={runPreview} disabled={!importText.trim()}>Vorschau</Btn>
          {preview && preview.length > 0 && <Btn small variant="primary" onClick={applyImport}>{preview.length} Tage übernehmen</Btn>}
        </div>
        {preview && preview.length > 0 && (
          <div className="trn-import-prev">
            {preview.slice(0, 6).map((r) => (
              <div key={r.date} className="trn-import-row">
                <span>{r.date}</span>
                <span className="trn-mono-sm">{r.kcal ?? "–"} kcal · {r.protein ?? "–"} P · {r.carbs ?? "–"} C · {r.fat ?? "–"} F</span>
              </div>
            ))}
            {preview.length > 6 && <div className="trn-mini-label">… und {preview.length - 6} weitere</div>}
          </div>
        )}
        {preview && preview.length === 0 && <div className="trn-mini-label" style={{ marginTop: 8 }}>Keine gültigen Zeilen erkannt — prüfe das Format.</div>}
      </Card>

      {/* iPhone */}
      <Card>
        <Eyebrow>Auf dem iPhone nutzen</Eyebrow>
        <div className="trn-help">
          <p><b>Schnellster Weg:</b> Öffne dieses Dashboard in der Claude-App und tippe oben rechts auf „Veröffentlichen". Öffne den erzeugten Link in <b>Safari</b>, dann Teilen-Symbol → <b>„Zum Home-Bildschirm"</b>. So bekommst du ein Icon, das direkt hierher springt.</p>
          <p><b>Alternativ:</b> Claude-App aufs Home-Menü legen und dieses Gespräch anpinnen.</p>
          <p className="trn-mini-label">Für eine komplett eigenständige App mit Icon (unabhängig von Claude) baue ich dir auf Wunsch eine installierbare Web-App, die du z. B. über GitLab Pages hostest — sag einfach Bescheid.</p>
        </div>
      </Card>

      <Card>
        <Eyebrow>Daten</Eyebrow>
        {!confirmReset ? <Btn variant="danger" onClick={() => setConfirmReset(true)}>Alle Daten löschen</Btn> : (
          <div>
            <div className="trn-warn" style={{ marginBottom: 10 }}>Löscht Einträge, Plan und Einstellungen unwiderruflich und stellt die Standardwerte wieder her.</div>
            <div style={{ display: "flex", gap: 8 }}><Btn variant="danger" onClick={resetAll}>Ja, alles löschen</Btn><Btn onClick={() => setConfirmReset(false)}>Abbrechen</Btn></div>
          </div>
        )}
      </Card>

      <div className="trn-footer">12-Wochen-Block · Sweet Spot → Schwelle → VO2max · Deload W4/W8 · Taper W12</div>
    </div>
  );
}

/* ============================== STYLES ================================= */
function Style() {
  return (
    <style>{`
    .trn {
      --bg:#0F131A; --surface:#181E27; --surface2:#212A36; --raised:#28323F;
      --border:#28313D; --border2:#3A4653;
      --txt:#E9EEF4; --dim:#9AA7B6; --faint:#66737F;
      --accent:#4C90D9; --accent2:#2F6DB0; --violet:#9A86E0;
      --z1:#7C8B9E; --z2:#4C90D9; --z3:#46B37A; --z4:#E5B143; --z5:#E8823C; --z6:#DE5A5A;
      --green:#46B37A; --amber:#E5B143; --red:#DE5A5A;
      --mono: ui-monospace,"SF Mono","JetBrains Mono",Menlo,monospace;
      --sans: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
      font-family: var(--sans); color: var(--txt); background: var(--bg);
      -webkit-font-smoothing: antialiased; min-height:100vh;
    }
    .trn *{box-sizing:border-box;}
    .trn-shell{max-width:520px;margin:0 auto;min-height:100vh;display:flex;flex-direction:column;position:relative;background:var(--bg);}
    .trn-content{flex:1;padding:14px 14px 92px;}
    .trn-stack{display:flex;flex-direction:column;gap:12px;}

    .trn-header{position:sticky;top:0;z-index:20;display:flex;justify-content:space-between;align-items:center;padding:14px 16px;background:rgba(15,19,26,0.92);backdrop-filter:blur(10px);border-bottom:1px solid var(--border);}
    .trn-brand{font-family:var(--mono);font-weight:700;letter-spacing:4px;font-size:15px;}
    .trn-header-sub{font-size:11px;color:var(--dim);margin-top:2px;font-family:var(--mono);letter-spacing:.3px;}
    .trn-header-week{text-align:right;display:flex;flex-direction:column;align-items:flex-end;}
    .trn-header-week-num{font-family:var(--mono);font-size:20px;font-weight:700;color:var(--accent);line-height:1;}
    .trn-header-week-lab{font-size:10px;color:var(--faint);text-transform:uppercase;letter-spacing:.6px;margin-top:3px;}

    .trn-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:14px;}
    .trn-eyebrow{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:1.4px;}
    .trn-row-between{display:flex;justify-content:space-between;align-items:center;gap:8px;}
    .trn-mini-label{font-size:11px;color:var(--faint);}
    .trn-hint{font-size:11px;color:var(--faint);margin-top:10px;line-height:1.5;}
    .trn-empty{font-size:13px;color:var(--dim);padding:6px 0;line-height:1.5;}
    .trn-warn{background:rgba(222,90,90,0.10);border:1px solid rgba(222,90,90,0.35);color:#f0b5b5;font-size:12px;padding:10px 12px;border-radius:10px;line-height:1.45;}

    .trn-datenav{display:flex;align-items:center;gap:10px;}
    .trn-datenav-center{flex:1;text-align:center;}
    .trn-datenav-date{font-size:14px;font-weight:600;}
    .trn-nav-btn{width:40px;height:40px;flex:none;border-radius:11px;background:var(--surface);border:1px solid var(--border);color:var(--txt);font-size:20px;cursor:pointer;line-height:1;}
    .trn-nav-btn:active{background:var(--surface2);}
    .trn-today-jump{background:none;border:none;color:var(--accent);font-size:11px;cursor:pointer;margin-top:2px;font-weight:600;}

    .trn-override-banner{display:flex;justify-content:space-between;align-items:center;gap:8px;background:rgba(76,144,217,0.12);border:1px solid rgba(76,144,217,0.4);border-radius:10px;padding:9px 12px;font-size:12px;color:#bcd6f2;}
    .trn-override-banner button{background:none;border:none;color:var(--accent);font-weight:600;font-size:12px;cursor:pointer;}
    .trn-replace-btn{width:100%;background:var(--surface);border:1px dashed var(--border2);color:var(--dim);border-radius:12px;padding:11px;font-size:13px;font-weight:600;cursor:pointer;font-family:var(--sans);}
    .trn-replace-btn:active{background:var(--surface2);}

    .trn-pill{font-family:var(--mono);font-size:12px;font-weight:600;padding:2px 9px;border:1px solid;border-radius:20px;}
    .trn-ride-name{font-size:21px;font-weight:700;margin:8px 0 2px;letter-spacing:-.2px;}
    .trn-readout{margin:12px 0 8px;padding:14px;border:1px solid;border-radius:12px;background:linear-gradient(180deg,rgba(255,255,255,0.02),rgba(0,0,0,0.15));text-align:center;}
    .trn-readout-main{display:flex;align-items:baseline;justify-content:center;gap:6px;}
    .trn-readout-num{font-family:var(--mono);font-size:46px;font-weight:700;line-height:1;letter-spacing:-1px;}
    .trn-readout-dash{font-size:30px;opacity:.5;padding:0 2px;}
    .trn-readout-unit{font-family:var(--mono);font-size:18px;color:var(--dim);font-weight:600;}
    .trn-readout-sub{font-size:11px;color:var(--dim);margin-top:6px;font-family:var(--mono);letter-spacing:.4px;}
    .trn-ride-int{font-size:13.5px;color:var(--txt);opacity:.9;line-height:1.5;margin-top:4px;}
    .trn-gauges{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:14px;padding-top:12px;border-top:1px solid var(--border);}
    .trn-gauge{text-align:center;}
    .trn-gauge-label{font-size:9.5px;text-transform:uppercase;letter-spacing:.6px;color:var(--faint);}
    .trn-gauge-total{font-family:var(--mono);font-size:19px;font-weight:700;margin:3px 0 1px;}
    .trn-gauge-rate{font-size:10.5px;color:var(--dim);font-family:var(--mono);}

    .trn-phase-line{font-size:13px;color:var(--dim);margin:8px 0 4px;}
    .trn-phase-line b{color:var(--txt);}
    .trn-ex-list{margin-top:10px;display:flex;flex-direction:column;}
    .trn-ex-row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 0;border-top:1px solid var(--border);}
    .trn-ex-row:first-child{border-top:none;}
    .trn-ex-name{font-size:13.5px;line-height:1.35;display:flex;flex-direction:column;}
    .trn-ex-sr{font-family:var(--mono);font-size:11px;color:var(--dim);margin-top:1px;}
    .trn-ex-note{font-size:10.5px;color:var(--faint);margin-top:1px;}
    .trn-ex-input{display:flex;align-items:center;gap:4px;flex:none;}

    .trn-nut-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px;}
    .trn-nut-top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:5px;}
    .trn-nut-label{font-size:12px;font-weight:600;}
    .trn-nut-target{font-size:10px;color:var(--faint);font-family:var(--mono);}
    .trn-nut-inputrow{display:flex;align-items:center;gap:4px;margin-bottom:6px;}

    .trn-input{background:var(--surface2);border:1px solid var(--border2);border-radius:9px;color:var(--txt);font-size:14px;padding:9px 11px;width:100%;font-family:var(--sans);outline:none;}
    .trn-input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(76,144,217,0.15);}
    .trn-input-num{width:64px;text-align:right;font-family:var(--mono);padding:8px 9px;}
    .trn-input-num.wide{width:78px;}
    .trn-suffix{font-size:12px;color:var(--faint);font-family:var(--mono);}
    .trn-select{background:var(--surface2);border:1px solid var(--border2);border-radius:9px;color:var(--txt);font-size:13px;padding:9px 11px;width:100%;outline:none;font-family:var(--sans);margin-top:8px;}
    .trn-select.sm{margin-top:0;padding:7px 9px;font-size:12px;width:auto;}
    .trn-select:focus{border-color:var(--accent);}
    .trn-textarea{background:var(--surface2);border:1px solid var(--border2);border-radius:9px;color:var(--txt);font-size:13px;padding:10px 11px;width:100%;outline:none;font-family:var(--sans);resize:vertical;min-height:52px;margin-top:10px;line-height:1.4;}
    .trn-textarea.sm{min-height:44px;margin-top:0;}
    .trn-textarea:focus{border-color:var(--accent);}
    .trn-field{display:flex;flex-direction:column;gap:5px;}
    .trn-field-label{font-size:11px;color:var(--dim);font-weight:500;}
    .trn-field-input{display:flex;align-items:center;gap:6px;}
    .trn-check{display:flex;align-items:center;gap:9px;font-size:14px;font-weight:600;cursor:pointer;}
    .trn-check input{width:19px;height:19px;accent-color:var(--green);}
    .trn-weight-inline{display:flex;align-items:center;gap:6px;}

    .trn-bar{height:5px;background:var(--surface2);border-radius:3px;overflow:hidden;}
    .trn-bar-fill{height:100%;border-radius:3px;transition:width .3s ease;}

    .trn-seg{display:flex;background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:3px;gap:3px;}
    .trn-seg-btn{flex:1;border:none;background:none;color:var(--dim);font-size:12.5px;font-weight:600;padding:8px 4px;border-radius:7px;cursor:pointer;font-family:var(--sans);}
    .trn-seg-btn.active{background:var(--accent);color:#fff;}

    .trn-btn{background:var(--surface2);border:1px solid var(--border2);color:var(--txt);font-size:13px;font-weight:600;padding:9px 14px;border-radius:9px;cursor:pointer;font-family:var(--sans);}
    .trn-btn:active{transform:translateY(1px);}
    .trn-btn:disabled{opacity:.4;cursor:not-allowed;}
    .trn-btn-primary{background:var(--accent);border-color:var(--accent);color:#fff;}
    .trn-btn-danger{background:rgba(222,90,90,0.12);border-color:rgba(222,90,90,0.4);color:#f0a3a3;}

    .trn-status-dot{width:11px;height:11px;border-radius:50%;}
    .trn-trend-main{display:flex;justify-content:space-between;align-items:flex-end;margin:10px 0 12px;}
    .trn-trend-num{font-family:var(--mono);font-size:38px;font-weight:700;line-height:1;}
    .trn-trend-unit{font-size:16px;color:var(--dim);margin-left:5px;}
    .trn-trend-rate{text-align:right;}
    .trn-trend-rate-num{font-family:var(--mono);font-size:24px;font-weight:700;line-height:1;}
    .trn-spark{width:100%;height:70px;display:block;}
    .trn-spark-empty{font-size:12px;color:var(--faint);padding:20px 0;text-align:center;}
    .trn-goal-row{display:flex;align-items:center;margin:12px 0 8px;}
    .trn-mono-sm{font-family:var(--mono);font-size:12px;color:var(--dim);}
    .trn-goal-cur{font-size:12.5px;color:var(--dim);}
    .trn-goal-cur b{color:var(--txt);}
    .trn-week-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px;}
    .trn-wstat{background:var(--surface2);border-radius:10px;padding:12px 8px;text-align:center;}
    .trn-wstat-val{font-family:var(--mono);font-size:19px;font-weight:700;}
    .trn-wstat-lab{font-size:10px;color:var(--faint);text-transform:uppercase;letter-spacing:.4px;margin-top:3px;}

    .trn-macro-grid{margin-top:12px;display:flex;flex-direction:column;gap:6px;}
    .trn-macro-head,.trn-macro-row{display:grid;grid-template-columns:52px repeat(7,1fr) 34px;gap:4px;align-items:center;}
    .trn-macro-wd{font-size:9.5px;color:var(--faint);text-align:center;}
    .trn-macro-avg-h{font-size:9.5px;color:var(--faint);text-align:center;}
    .trn-macro-rowlabel{font-size:11px;color:var(--dim);font-weight:600;}
    .trn-macro-cell{font-family:var(--mono);font-size:9.5px;text-align:center;padding:5px 0;border:1px solid var(--border2);border-radius:5px;color:var(--txt);overflow:hidden;}
    .trn-macro-avg{font-family:var(--mono);font-size:10.5px;text-align:center;color:var(--dim);}
    .trn-macro-legend{display:flex;gap:12px;margin-top:10px;flex-wrap:wrap;}
    .trn-macro-legend span{display:flex;align-items:center;gap:5px;font-size:10.5px;color:var(--faint);}
    .trn-macro-legend i{width:9px;height:9px;border-radius:2px;display:inline-block;}

    .trn-strhist{margin-top:12px;display:flex;flex-direction:column;gap:8px;}
    .trn-strhist-row{display:flex;align-items:center;gap:10px;}
    .trn-strhist-wk{font-family:var(--mono);font-size:11px;color:var(--faint);width:26px;}
    .trn-strhist-bar{flex:1;height:8px;background:var(--surface2);border-radius:4px;overflow:hidden;}
    .trn-strhist-bar div{height:100%;background:var(--violet);border-radius:4px;}
    .trn-strhist-val{font-family:var(--mono);font-size:12px;width:56px;text-align:right;}

    .trn-weeksel{display:flex;align-items:center;gap:10px;}
    .trn-weeksel-mid{flex:1;text-align:center;}
    .trn-weeksel-num{font-size:16px;font-weight:700;}
    .trn-weekdots{display:grid;grid-template-columns:repeat(12,1fr);gap:4px;margin-top:12px;}
    .trn-weekdot{aspect-ratio:1;border:1px solid var(--border2);background:var(--surface2);color:var(--dim);border-radius:7px;font-size:11px;font-family:var(--mono);cursor:pointer;padding:0;}
    .trn-weekdot.active{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:700;}
    .trn-day-head{display:flex;align-items:center;gap:10px;width:100%;background:none;border:none;color:var(--txt);padding:13px 14px;cursor:pointer;text-align:left;}
    .trn-day-wd{font-family:var(--mono);font-size:12px;font-weight:700;color:var(--faint);width:24px;flex:none;}
    .trn-day-name{flex:1;font-size:14px;font-weight:600;}
    .trn-day-chev{color:var(--faint);font-size:12px;}
    .trn-day-body{padding:0 14px 14px;border-top:1px solid var(--border);padding-top:12px;}
    .trn-edit-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px;}
    .trn-day-actions{display:flex;justify-content:space-between;align-items:flex-end;gap:10px;margin-top:14px;flex-wrap:wrap;}
    .trn-move{display:flex;flex-direction:column;gap:5px;font-size:11px;color:var(--dim);}
    .trn-week-actions{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:10px;flex-wrap:wrap;}
    .trn-dup{display:flex;gap:8px;align-items:center;}

    .trn-ex-edit-list{display:flex;flex-direction:column;gap:12px;margin-top:12px;}
    .trn-ex-edit{display:flex;flex-direction:column;gap:6px;}
    .trn-ex-edit-main{display:flex;align-items:center;gap:8px;}
    .trn-ex-move{display:flex;flex-direction:column;gap:2px;}
    .trn-ex-move button{width:22px;height:16px;font-size:8px;line-height:1;background:var(--surface2);border:1px solid var(--border2);color:var(--dim);border-radius:4px;cursor:pointer;padding:0;}
    .trn-ex-move button:disabled{opacity:.3;}
    .trn-del{width:30px;height:30px;flex:none;background:rgba(222,90,90,0.12);border:1px solid rgba(222,90,90,0.3);color:#e88;border-radius:8px;cursor:pointer;font-size:12px;}
    .trn-ex-edit-sr{display:flex;align-items:center;gap:6px;padding-left:32px;}
    .trn-sr-lab{font-size:10.5px;color:var(--faint);}
    .trn-sr-inp{width:58px;text-align:center;padding:6px 6px;font-size:12px;}
    .trn-sr-x{color:var(--faint);}
    .trn-sr-hint{font-size:10px;color:var(--faint);margin-left:auto;}
    .trn-phase-edit{display:flex;flex-direction:column;gap:14px;margin-top:12px;}
    .trn-phase-title{font-size:13px;font-weight:700;margin-bottom:8px;}
    .trn-phase-fields{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;}
    .trn-phase-fields .trn-input{padding:7px 8px;font-size:12px;text-align:center;}

    .trn-ovr-ex-head{display:grid;grid-template-columns:1fr 58px 58px 30px;gap:6px;font-size:10px;color:var(--faint);text-transform:uppercase;letter-spacing:.5px;margin-bottom:5px;padding:0 2px;}
    .trn-ovr-ex-row{display:grid;grid-template-columns:1fr 58px 58px 30px;gap:6px;margin-bottom:6px;align-items:center;}
    .trn-ovr-sr{text-align:center;padding:8px 6px;}
    .trn-import-prev{margin-top:12px;background:var(--surface2);border-radius:9px;padding:10px 12px;display:flex;flex-direction:column;gap:6px;}
    .trn-import-row{display:flex;justify-content:space-between;gap:8px;font-size:12px;}
    .trn-help{margin-top:8px;display:flex;flex-direction:column;gap:9px;}
    .trn-help p{font-size:12.5px;color:var(--dim);line-height:1.55;margin:0;}
    .trn-help b{color:var(--txt);}

    .trn-footer{text-align:center;font-size:10.5px;color:var(--faint);font-family:var(--mono);letter-spacing:.3px;line-height:1.5;padding:10px 0;}

    .trn-tabbar{position:fixed;bottom:0;left:0;right:0;max-width:520px;margin:0 auto;display:flex;background:rgba(20,25,33,0.96);backdrop-filter:blur(12px);border-top:1px solid var(--border);z-index:30;}
    .trn-tab{flex:1;background:none;border:none;color:var(--faint);padding:9px 0 max(9px,env(safe-area-inset-bottom));display:flex;flex-direction:column;align-items:center;gap:3px;font-size:10.5px;cursor:pointer;font-family:var(--sans);}
    .trn-tab.active{color:var(--accent);}
    .trn-tab-icon{font-size:18px;line-height:1;}

    .trn-toast{position:fixed;bottom:78px;left:50%;transform:translateX(-50%);background:var(--raised);border:1px solid var(--border2);color:var(--txt);font-size:13px;padding:10px 18px;border-radius:22px;z-index:50;box-shadow:0 8px 24px rgba(0,0,0,.4);}
    .trn-spinner{width:34px;height:34px;border:3px solid var(--border2);border-top-color:var(--accent);border-radius:50%;margin:0 auto;animation:trn-spin .8s linear infinite;}
    @keyframes trn-spin{to{transform:rotate(360deg);}}
    @media (prefers-reduced-motion: reduce){.trn-spinner{animation-duration:2s;} .trn-bar-fill{transition:none;}}
    `}</style>
  );
}
