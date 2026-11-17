// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { api, CaseDate, CaseSummary, Question, Suggestion } from "../api";
import type { OpenPage } from "../pages/CaseView";
import Ablauf from "./Ablauf";
import Formelles from "./Formelles";
import AnalysisBar from "./AnalysisBar";
import CiteLinks from "./CiteLinks";

const FIELD_LABEL: Record<string, string> = {
  auftraggeber: "Auftraggeber",
  aktenzeichen: "Aktenzeichen",
  patient_name: "Proband/in",
  patient_dob: "Geburtsdatum",
  accident_date: "Unfalldatum",
};

function suggestionText(s: Suggestion): string {
  const p = s.payload;
  if (s.kind === "case_field") return `${FIELD_LABEL[p.field] ?? p.field}: ${p.value}`;
  if (s.kind === "date") return `${KIND_LABEL[p.kind] ?? p.kind} ${p.date}${p.label ? ` · ${p.label}` : ""}`;
  return `Beweisfrage: ${p.text}`;
}

const KIND_LABEL: Record<string, string> = {
  begutachtung: "Begutachtung",
  frist: "Frist",
  termin: "Termin",
  sonstiges: "Termin",
};

export default function UebersichtTab({
  case_,
  onChanged,
  openPage,
}: {
  case_: CaseSummary;
  onChanged: () => void;
  openPage: OpenPage;
}) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [form, setForm] = useState(case_);
  const [dates, setDates] = useState<CaseDate[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [dKind, setDKind] = useState("termin");
  const [dDate, setDDate] = useState("");
  const [dLabel, setDLabel] = useState("");
  const [qText, setQText] = useState("");

  useEffect(() => setForm(case_), [case_]);
  const reload = () => {
    api.listDates(case_.id).then(setDates);
    api.listQuestions(case_.id).then(setQuestions);
    api.getSuggestions(case_.id).then(setSuggestions);
  };

  const decide = async (s: Suggestion, accept: boolean) => {
    await api.decideSuggestion(case_.id, s.id, accept);
    reload();
    onChanged();
  };
  const open = suggestions.filter((s) => s.status === "open");
  useEffect(reload, [case_.id]);

  const save = async () => {
    await api.updateCase(case_.id, {
      title: form.title,
      patient_ref: form.patient_ref,
      patient_dob: form.patient_dob,
      jurisdiction: form.jurisdiction,
      case_type: form.case_type,
      accident_date: form.accident_date,
      auftraggeber: form.auftraggeber,
      notes: form.notes,
      job_profile: form.job_profile,
    });
    onChanged();
  };

  const addDate = async () => {
    if (!dDate) return;
    await api.addDate(case_.id, dKind, dDate, dLabel);
    setDLabel("");
    setDDate("");
    reload();
    onChanged();
  };

  const addQuestion = async () => {
    if (!qText.trim()) return;
    await api.addQuestion(case_.id, questions.length + 1, qText.trim());
    setQText("");
    reload();
  };

  return (
    <div className="tab-body uebersicht">
      <Ablauf case_={case_} onChanged={() => { reload(); onChanged(); }} />
      <div className="panel span-all">
        <h3>Vorschläge aus dem Gutachtenauftrag</h3>
        <AnalysisBar
          caseId={case_.id}
          steps={["cover"]}
          label="Gutachtenauftrag auslesen"
          onDone={reload}
          describe={(r) =>
            `${r.cover?.suggestions ?? 0} Vorschläge, davon ${r.cover?.verified ?? 0} im Text belegt.`
          }
        />
        {open.length === 0 && (
          <p className="muted small">
            Liest die ersten Seiten der Akte (Auftrag / Beweisbeschluss) und schlägt
            Falldaten, Fristen und Beweisfragen vor. Vorschläge gelten erst nach Bestätigung.
          </p>
        )}
        <ul className="suggestions">
          {open.map((s) => (
            <li key={s.id} className={s.verified ? "" : "unverified"}>
              <span className="grow">
                {suggestionText(s)}
                {!s.verified && <span className="warn-note"> · nicht im Text belegt</span>}
              </span>
              {s.citation && <CiteLinks citations={[s.citation]} openPage={openPage} />}
              <button onClick={() => decide(s, true)}>Übernehmen</button>
              <button className="link" onClick={() => decide(s, false)}>
                Verwerfen
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="panel">
        <h3>Falldaten</h3>
        <div className="form-grid">
          <label>
            Bezeichnung
            <input
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
          </label>
          <label>
            Proband/in (Pseudonym)
            <input
              value={form.patient_ref ?? ""}
              onChange={(e) => setForm({ ...form, patient_ref: e.target.value })}
            />
          </label>
          <label>
            Geburtsdatum
            <input
              type="date"
              value={form.patient_dob ?? ""}
              onChange={(e) => setForm({ ...form, patient_dob: e.target.value })}
            />
          </label>
          <label>
            Unfalldatum
            <input
              type="date"
              value={form.accident_date ?? ""}
              onChange={(e) => setForm({ ...form, accident_date: e.target.value })}
            />
          </label>
          <label>
            Jurisdiktion
            <select
              value={form.jurisdiction}
              onChange={(e) => setForm({ ...form, jurisdiction: e.target.value })}
            >
              <option value="CH">Schweiz</option>
              <option value="AT">Österreich</option>
              <option value="DE">Deutschland</option>
            </select>
          </label>
          <label>
            Gutachtentyp
            <select
              value={form.case_type}
              onChange={(e) => setForm({ ...form, case_type: e.target.value })}
            >
              <option value="invaliditaet">Invalidenversicherung (IV) – Vorlage KSVI</option>
              <option value="unfall">Unfallversicherung (UVG)</option>
              <option value="haftpflicht">Haftpflicht / Gericht</option>
              <option value="sonstiges">Sonstiges</option>
            </select>
          </label>
          <label className="span2">
            Auftraggeber
            <input
              value={form.auftraggeber ?? ""}
              onChange={(e) => setForm({ ...form, auftraggeber: e.target.value })}
            />
          </label>
          <label className="span2">
            Anforderungsprofil bisherige Tätigkeit
            <textarea
              rows={2}
              value={form.job_profile ?? ""}
              onChange={(e) => setForm({ ...form, job_profile: e.target.value })}
            />
          </label>
          <label className="span2">
            Notizen
            <textarea
              rows={3}
              value={form.notes ?? ""}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
            />
          </label>
        </div>
        <button className="primary" onClick={save}>Speichern</button>
      </div>

      <Formelles case_={case_} onChanged={onChanged} />

      <div className="panel">
        <h3>Termine &amp; Fristen</h3>
        <div className="row">
          <select value={dKind} onChange={(e) => setDKind(e.target.value)}>
            <option value="begutachtung">Begutachtung</option>
            <option value="frist">Frist</option>
            <option value="termin">Termin</option>
          </select>
          <input type="date" value={dDate} onChange={(e) => setDDate(e.target.value)} />
          <input
            placeholder="Notiz"
            value={dLabel}
            onChange={(e) => setDLabel(e.target.value)}
          />
          <button onClick={addDate}>+</button>
        </div>
        <ul className="datelist">
          {dates.map((d) => (
            <li key={d.id} className={d.done ? "done" : ""}>
              <label>
                <input
                  type="checkbox"
                  checked={!!d.done}
                  onChange={(e) =>
                    api.setDateDone(case_.id, d.id, e.target.checked).then(reload)
                  }
                />
                <strong>{d.date}</strong> · {KIND_LABEL[d.kind] ?? d.kind}
                {d.label ? ` · ${d.label}` : ""}
              </label>
              <button
                className="link"
                onClick={() => api.deleteDate(case_.id, d.id).then(reload)}
              >
                ✕
              </button>
            </li>
          ))}
          {dates.length === 0 && <li className="muted">Keine Termine eingetragen.</li>}
        </ul>
      </div>

      <div className="panel">
        <h3>Fragenkatalog / Beweisfragen</h3>
        <div className="row">
          <input
            placeholder="Frage des Auftraggebers hinzufügen"
            value={qText}
            onChange={(e) => setQText(e.target.value)}
            style={{ flex: 1 }}
          />
          <button onClick={addQuestion}>+</button>
        </div>
        <ol className="questions">
          {questions.map((q) => (
            <li key={q.id} className={q.status}>
              {q.text} <span className="muted">({q.status})</span>
            </li>
          ))}
          {questions.length === 0 && (
            <li className="muted">Noch keine Fragen. Werden später aus dem Beweisbeschluss eingelesen.</li>
          )}
        </ol>
      </div>
    </div>
  );
}
