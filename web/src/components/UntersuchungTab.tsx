// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { api, CaseSummary, deDate, Diagnosis, DiagnosisSuggestion, errorText } from "../api";
import type { OpenPage } from "../pages/CaseView";
import InterviewPanel from "./InterviewPanel";

// Standard movements per joint, Neutral-0-Methode
const ROM_PRESETS: Record<string, string[]> = {
  Schulter: ["Abduktion/Adduktion", "Anteversion/Retroversion",
    "Aussenrotation/Innenrotation (Arm anliegend)"],
  Ellbogen: ["Extension/Flexion", "Pronation/Supination"],
  Handgelenk: ["Extension/Flexion", "Radialabduktion/Ulnarabduktion"],
  Hüfte: ["Extension/Flexion", "Abduktion/Adduktion", "Aussenrotation/Innenrotation"],
  Knie: ["Extension/Flexion"],
  OSG: ["Dorsalextension/Plantarflexion"],
  USG: ["Eversion/Inversion (Bruchteil)"],
  HWS: ["Flexion/Extension", "Seitneigung rechts/links", "Rotation rechts/links"],
  LWS: ["Finger-Boden-Abstand (cm)", "Schober (cm)", "Seitneigung rechts/links"],
};
const UMFANG_PRESETS: Record<string, string[]> = {
  Bein: ["20 cm oberhalb Kniegelenkspalt", "10 cm oberhalb Kniegelenkspalt",
    "Kniegelenkspalt", "15 cm unterhalb Kniegelenkspalt", "Knöchel"],
  Arm: ["15 cm oberhalb Epicondylus lateralis", "Ellbogen", "10 cm unterhalb Epicondylus",
    "Handgelenk"],
};
const TEST_PRESETS: Record<string, string[]> = {
  Knie: ["Lachman", "Vordere Schublade", "Hintere Schublade", "Pivot-Shift", "McMurray",
    "Steinmann I", "Valgusstress 30°", "Varusstress 30°", "Erguss (Tanzende Patella)"],
  Schulter: ["Jobe", "Neer", "Hawkins-Kennedy", "Lift-off", "Belly-press", "Speed",
    "O'Brien", "Apprehension"],
  Wirbelsäule: ["Lasègue", "Bragard", "Femoralisdehnung", "Spurling"],
};
const FREQ = ["uneingeschränkt", "häufig", "gelegentlich", "selten", "nicht zumutbar"];

type Row = Record<string, string>;
type Exam = {
  methode?: string; allgemein?: string; gang?: string; verhalten?: string;
  rom?: Row[]; umfang?: Row[]; tests?: Row[]; neuro?: string; weitere?: string; zusatz?: string;
};
type AF = Record<string, string | number | undefined>;
type Answers = {
  bisherige?: AF; angepasst?: AF; profil?: AF; massnahmen?: AF; uv?: AF; at?: AF;
  therapieverlauf?: string; faehigkeiten?: string;
};

function SideTable({ rows, cols, onChange }: {
  rows: Row[]; cols: [string, string][]; onChange: (r: Row[]) => void;
}) {
  const set = (i: number, k: string, v: string) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  return (
    <table className="cases exam-table">
      <thead><tr>{cols.map(([, l]) => <th key={l}>{l}</th>)}<th /></tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="no-hover">
            {cols.map(([k]) => (
              <td key={k}><input value={r[k] ?? ""} onChange={(e) => set(i, k, e.target.value)} /></td>
            ))}
            <td><button className="link" onClick={() => onChange(rows.filter((_, j) => j !== i))}>✕</button></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ExamPanel({ caseId }: { caseId: string }) {
  const [ex, setEx] = useState<Exam>({});
  const [msg, setMsg] = useState("");
  useEffect(() => { api.getExam(caseId).then((d) => setEx(d as Exam)); }, [caseId]);
  const save = async () => {
    try { await api.putExam(caseId, ex); setMsg("Gespeichert – wird beim nächsten Entwurf übernommen."); }
    catch (e) { setMsg(errorText(e)); }
  };
  const add = (key: "rom" | "umfang" | "tests", rows: Row[]) =>
    setEx({ ...ex, [key]: [...(ex[key] ?? []), ...rows] });
  const text = (k: keyof Exam, label: string, rows = 2) => (
    <label className="span2">{label}
      <textarea rows={rows} value={(ex[k] as string) ?? ""}
        onChange={(e) => setEx({ ...ex, [k]: e.target.value })} />
    </label>
  );
  return (
    <div className="panel">
      <h3>Untersuchungsbefund</h3>
      <p className="muted small">Erzeugt den Abschnitt „Befund“ mit Methode und Messwerten
        (Neutral-0-Methode, Umfangmasse). Leere Zeilen werden weggelassen.</p>
      <div className="form-grid">
        {text("verhalten", "Verhalten und äussere Erscheinung")}
        {text("allgemein", "Allgemeinbefund")}
        {text("gang", "Gangbild", 1)}
      </div>
      <h4>Bewegungsumfang (Grad, rechts / links)</h4>
      <div className="row wrap">
        {Object.keys(ROM_PRESETS).map((g) => (
          <button key={g} onClick={() => add("rom", ROM_PRESETS[g].map((b) =>
            ({ gelenk: g, bewegung: b, rechts: "", links: "" })))}>+ {g}</button>
        ))}
      </div>
      {(ex.rom?.length ?? 0) > 0 && <SideTable rows={ex.rom!} onChange={(r) => setEx({ ...ex, rom: r })}
        cols={[["gelenk", "Gelenk"], ["bewegung", "Bewegung"], ["rechts", "rechts"], ["links", "links"]]} />}
      <h4>Umfangmasse (cm)</h4>
      <div className="row wrap">
        {Object.keys(UMFANG_PRESETS).map((g) => (
          <button key={g} onClick={() => add("umfang", UMFANG_PRESETS[g].map((s) =>
            ({ stelle: s, rechts: "", links: "" })))}>+ {g}</button>
        ))}
      </div>
      {(ex.umfang?.length ?? 0) > 0 && <SideTable rows={ex.umfang!} onChange={(r) => setEx({ ...ex, umfang: r })}
        cols={[["stelle", "Messstelle"], ["rechts", "rechts"], ["links", "links"]]} />}
      <h4>Klinische Tests</h4>
      <div className="row wrap">
        {Object.keys(TEST_PRESETS).map((g) => (
          <button key={g} onClick={() => add("tests", TEST_PRESETS[g].map((t) =>
            ({ test: t, rechts: "", links: "" })))}>+ {g}</button>
        ))}
        <button onClick={() => add("tests", [{ test: "", rechts: "", links: "" }])}>+ Test</button>
      </div>
      {(ex.tests?.length ?? 0) > 0 && <SideTable rows={ex.tests!} onChange={(r) => setEx({ ...ex, tests: r })}
        cols={[["test", "Test"], ["rechts", "rechts"], ["links", "links"]]} />}
      <div className="form-grid">
        {text("neuro", "Neurostatus")}
        {text("weitere", "Weitere Befunde")}
        {text("zusatz", "Eigene Zusatzuntersuchungen (z. B. Röntgen am Untersuchungstag)")}
      </div>
      <div className="row"><button className="primary" onClick={save}>Befund speichern</button>
        {msg && <span className="muted small">{msg}</span>}</div>
    </div>
  );
}

function DiagnosesPanel({ caseId, openPage }: { caseId: string; openPage: OpenPage }) {
  const [rows, setRows] = useState<Diagnosis[]>([]);
  const [sugg, setSugg] = useState<DiagnosisSuggestion[]>([]);
  const [text, setText] = useState("");
  const [code, setCode] = useState("");
  const [hits, setHits] = useState<{ code: string; text: string }[]>([]);
  const [msg, setMsg] = useState("");
  const load = () => {
    api.getDiagnoses(caseId).then(setRows);
    api.diagnosisSuggestions(caseId).then(setSugg);
  };
  useEffect(load, [caseId]);
  useEffect(() => {
    const q = code || text;
    if (q.length < 2) { setHits([]); return; }
    const t = setTimeout(() => api.icd10(q).then((r) => setHits(r.results)), 200);
    return () => clearTimeout(t);
  }, [code, text]);

  const add = async (d: Partial<Diagnosis>) => {
    try { await api.addDiagnosis(caseId, d); setText(""); setCode(""); setMsg(""); load(); }
    catch (e) { setMsg(errorText(e)); }
  };
  const update = async (d: Diagnosis, patch: Partial<Diagnosis>) => {
    try { await api.updateDiagnosis(caseId, d.id, { ...d, ...patch }); setMsg(""); load(); }
    catch (e) { setMsg(errorText(e)); }
  };

  return (
    <div className="panel">
      <h3>Diagnosen (ICD-10)</h3>
      <p className="muted small">Codierung nach ICD-10-GM ist Pflicht; ohne Code lässt sich der
        Abschnitt nicht freigeben. Vorschläge stammen aus belegten Angaben der Akte.</p>
      <ol className="diag-list">
        {rows.map((d) => (
          <li key={d.id}>
            <input className="diag-text" value={d.text}
              onChange={(e) => setRows(rows.map((x) => x.id === d.id ? { ...x, text: e.target.value } : x))}
              onBlur={() => update(d, {})} />
            <input className={`diag-code ${d.icd10 ? "" : "missing"}`} placeholder="ICD-10"
              value={d.icd10 ?? ""}
              onChange={(e) => setRows(rows.map((x) => x.id === d.id ? { ...x, icd10: e.target.value } : x))}
              onBlur={(e) => update(d, { icd10: e.target.value || null })} />
            <select value={d.af_relevant ?? ""} onChange={(e) =>
              update(d, { af_relevant: e.target.value === "" ? null : Number(e.target.value) })}>
              <option value="">Auswirkung auf AF?</option>
              <option value="1">mit Auswirkung auf AF</option>
              <option value="0">ohne Auswirkung auf AF</option>
            </select>
            <button className="link" onClick={() => api.deleteDiagnosis(caseId, d.id).then(load)}>✕</button>
          </li>
        ))}
      </ol>
      <div className="row">
        <input style={{ flex: 2 }} placeholder="Diagnose" value={text} onChange={(e) => setText(e.target.value)} />
        <input style={{ width: 110 }} placeholder="ICD-10" value={code} onChange={(e) => setCode(e.target.value)} />
        <button disabled={!text.trim()} onClick={() => add({ text: text.trim(), icd10: code || null })}>+</button>
      </div>
      {hits.length > 0 && (
        <div className="icd-hits">
          {hits.map((h) => (
            <button key={h.code} className="cite" onClick={() => { setCode(h.code); if (!text) setText(h.text); }}>
              {h.code} {h.text}
            </button>
          ))}
        </div>
      )}
      {msg && <p className="warn-note">{msg}</p>}
      {sugg.length > 0 && (
        <details>
          <summary className="muted small">Vorschläge aus der Akte ({sugg.length})</summary>
          <ul className="suggestions">
            {sugg.map((s) => (
              <li key={s.fact_id}>
                <span className="grow">{s.title}{s.icd10 ? ` (${s.icd10})` : ""}
                  <span className="muted small"> · {deDate(s.fact_date)}</span></span>
                <button className="cite" onClick={() => openPage(s.global_seq)}>Bl. {s.global_seq}</button>
                <button onClick={() => add({ text: s.title, icd10: s.icd10, laterality: s.laterality,
                  source: "akte", fact_id: s.fact_id })}>Übernehmen</button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function AnswersPanel({ case_ }: { case_: CaseSummary }) {
  const [a, setA] = useState<Answers>({});
  const [msg, setMsg] = useState("");
  useEffect(() => { api.getAnswers(case_.id).then((d) => setA(d as Answers)); }, [case_.id]);
  const set = (group: keyof Answers, k: string, v: string) =>
    setA({ ...a, [group]: { ...((a[group] as AF) ?? {}), [k]: v } });
  const val = (group: keyof Answers, k: string) => ((a[group] as AF)?.[k] ?? "") as string;
  const num = (g: keyof Answers, k: string, label: string, w = 90) => (
    <label>{label}<input type="number" style={{ width: w }} value={val(g, k)}
      onChange={(e) => set(g, k, e.target.value)} /></label>
  );
  const txt = (g: keyof Answers, k: string, label: string) => (
    <label className="span2">{label}<input value={val(g, k)} onChange={(e) => set(g, k, e.target.value)} /></label>
  );
  const sel = (g: keyof Answers, k: string, label: string, opts: [string, string][]) => (
    <label>{label}<select value={val(g, k)} onChange={(e) => set(g, k, e.target.value)}>
      <option value="">—</option>{opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select></label>
  );
  const af = (g: "bisherige" | "angepasst", title: string) => {
    const p = val(g, "af_pct");
    return (
      <div className="answer-block">
        <h4>{title}</h4>
        <div className="form-grid">
          {g === "angepasst" && txt(g, "merkmale", "Merkmale der angepassten Tätigkeit")}
          {num(g, "praesenz_h", "Präsenz (Std./Tag)")}
          {num(g, "leistung_einschraenkung_pct", "Leistungseinschränkung (%)")}
          {txt(g, "einschraenkung_grund", "Grund der Leistungseinschränkung")}
          <label>Arbeitsfähigkeit (%)<input type="number" style={{ width: 90 }} value={p}
            onChange={(e) => set(g, "af_pct", e.target.value)} />
            {p !== "" && <span className="muted small">→ Arbeitsunfähigkeit {100 - Number(p)} %</span>}
          </label>
          {txt(g, "verlauf", "Zeitlicher Verlauf (seit wann, Entwicklung)")}
        </div>
      </div>
    );
  };
  const save = async () => {
    try { await api.putAnswers(case_.id, a); setMsg("Gespeichert – wird beim nächsten Entwurf übernommen."); }
    catch (e) { setMsg(errorText(e)); }
  };
  const uv = case_.case_type === "unfall" && case_.jurisdiction !== "AT";
  const at = case_.jurisdiction === "AT";
  return (
    <div className="panel">
      <h3>Standardfragen und Belastbarkeit</h3>
      <p className="muted small">Ihre Antworten auf die Standardfragen des Auftrags. Fehlende
        Antworten bleiben als Platzhalter stehen und sperren die Freigabe.</p>
      {uv && (
        <div className="answer-block">
          <h4>Unfallversicherung</h4>
          <div className="form-grid">
            {sel("uv", "kausalitaet", "Natürliche Kausalität", [
              ["ueberwiegend_wahrscheinlich", "überwiegend wahrscheinlich"],
              ["moeglich", "möglich (nicht überwiegend wahrscheinlich)"],
              ["unwahrscheinlich", "unwahrscheinlich"]])}
            {txt("uv", "kausalitaet_begruendung", "Begründung")}
            {sel("uv", "status_quo", "Status quo sine/ante", [["erreicht", "erreicht"],
              ["nicht_erreicht", "nicht erreicht"], ["nicht_beurteilbar", "nicht beurteilbar"]])}
            <label>Erreicht ab<input type="date" value={val("uv", "status_quo_datum")}
              onChange={(e) => set("uv", "status_quo_datum", e.target.value)} /></label>
            {sel("uv", "behandlungsabschluss", "Namhafte Besserung noch zu erwarten?",
              [["ja", "ja"], ["nein", "nein (Behandlungsabschluss)"]])}
            <label>Abschluss ab<input type="date" value={val("uv", "behandlungsabschluss_datum")}
              onChange={(e) => set("uv", "behandlungsabschluss_datum", e.target.value)} /></label>
            {num("uv", "integritaet_pct", "Integritätsschaden (%)")}
            {txt("uv", "integritaet_grundlage", "Grundlage (z. B. Suva-Tabelle)")}
          </div>
        </div>
      )}
      {at && (
        <div className="answer-block">
          <h4>Österreich (Grundgerüst, nicht verifiziert)</h4>
          <div className="form-grid">
            {num("at", "mde_pct", "MdE (%)")}
            <label>MdE ab<input type="date" value={val("at", "mde_ab")}
              onChange={(e) => set("at", "mde_ab", e.target.value)} /></label>
            {txt("at", "mde_begruendung", "Begründung MdE")}
            {num("at", "schmerzen_stark", "Schmerzen stark (Tage)")}
            {num("at", "schmerzen_mittel", "mittelstark (Tage)")}
            {num("at", "schmerzen_leicht", "leicht (Tage)")}
          </div>
        </div>
      )}
      {af("bisherige", "Arbeitsfähigkeit in der bisherigen Tätigkeit")}
      {af("angepasst", "Arbeitsfähigkeit in angepasster Tätigkeit")}
      <div className="answer-block">
        <h4>Belastbarkeitsprofil</h4>
        <div className="form-grid">
          {num("profil", "heben_selten_kg", "Heben/Tragen selten (kg)")}
          {num("profil", "heben_gelegentlich_kg", "gelegentlich (kg)")}
          {num("profil", "heben_haeufig_kg", "häufig (kg)")}
          {sel("profil", "haltung", "Arbeitshaltung", [["wechselbelastend", "wechselbelastend"],
            ["vorwiegend sitzend", "vorwiegend sitzend"], ["vorwiegend stehend", "vorwiegend stehend"]])}
          {txt("profil", "stehen_gehen_max", "Stehen/Gehen am Stück (z. B. 30 Min.)")}
          {txt("profil", "sitzen_max", "Sitzen am Stück")}
          {(["knien", "leitern", "ueberkopf", "gelaende", "treppen"] as const).map((k) =>
            sel("profil", k, { knien: "Knien/Hocken", leitern: "Leitern/Gerüste",
              ueberkopf: "Überkopfarbeiten", gelaende: "Unebenes Gelände", treppen: "Treppensteigen" }[k],
              FREQ.map((f) => [f, f] as [string, string])))}
          {txt("profil", "weitere", "Weitere Einschränkungen")}
        </div>
      </div>
      <div className="answer-block">
        <h4>Medizinische Massnahmen</h4>
        <div className="form-grid">
          {sel("massnahmen", "verbesserbar", "AF durch Massnahmen verbesserbar?", [["ja", "ja"], ["nein", "nein"]])}
          {txt("massnahmen", "begruendung", "Begründung (wenn nein)")}
          {txt("massnahmen", "optionen", "Therapieoptionen")}
          {txt("massnahmen", "dauer", "Dauer bis zum Erfolg")}
          {txt("massnahmen", "evidenz", "Evidenz / erwarteter Erfolg")}
          {txt("massnahmen", "risiken", "Medizinische Gründe/Risiken dagegen")}
        </div>
      </div>
      <div className="answer-block">
        <h4>Versicherungsmedizinische Beurteilung</h4>
        <div className="form-grid">
          <label className="span2">Therapieverlauf und Heilungschancen
            <textarea rows={3} value={a.therapieverlauf ?? ""}
              onChange={(e) => setA({ ...a, therapieverlauf: e.target.value })} /></label>
          <label className="span2">Fähigkeiten, Ressourcen und Belastungen
            <textarea rows={3} value={a.faehigkeiten ?? ""}
              onChange={(e) => setA({ ...a, faehigkeiten: e.target.value })} /></label>
        </div>
      </div>
      <div className="row"><button className="primary" onClick={save}>Antworten speichern</button>
        {msg && <span className="muted small">{msg}</span>}</div>
    </div>
  );
}

export default function UntersuchungTab({ case_, openPage }: {
  case_: CaseSummary; openPage: OpenPage;
}) {
  return (
    <div className="tab-body untersuchung">
      <InterviewPanel caseId={case_.id} openPage={openPage} />
      <ExamPanel caseId={case_.id} />
      <DiagnosesPanel caseId={case_.id} openPage={openPage} />
      <AnswersPanel case_={case_} />
    </div>
  );
}
