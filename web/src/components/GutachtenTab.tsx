// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { api, downloadFile, DraftSection, errorText, Question } from "../api";
import AnalysisBar from "./AnalysisBar";

const STATUS_LABEL: Record<string, string> = {
  empty: "leer",
  draft: "Entwurf",
  reviewed: "geprüft",
  approved: "freigegeben",
};
const KIND_LABEL: Record<string, string> = {
  data: "aus Falldaten",
  narrative: "KI-Entwurf mit Fundstellen",
  basis: "Entscheidungsgrundlage",
  questions: "Entscheidungsgrundlage je Frage",
  manual: "von Ihnen",
};

function Section({ caseId, s, onChanged }: {
  caseId: string;
  s: DraftSection;
  onChanged: () => void;
}) {
  const [text, setText] = useState(s.content_md);
  const [open, setOpen] = useState(s.status !== "approved");
  const [msg, setMsg] = useState("");
  useEffect(() => setText(s.content_md), [s.content_md]);
  const dirty = text !== s.content_md;

  const save = async (status?: string) => {
    setMsg("");
    try {
      await api.updateSection(caseId, s.section_key, {
        content_md: dirty ? text : undefined,
        status,
      });
      onChanged();
    } catch (e) {
      setMsg(errorText(e));
    }
  };

  return (
    <li className={`section st-${s.status}`}>
      <div className="section-head" onClick={() => setOpen(!open)}>
        <strong>{s.ord}. {s.title}</strong>
        <span className="muted small">{KIND_LABEL[s.kind] ?? s.kind}</span>
        <span className="grow" />
        {s.content_md.includes("⟦KI⟧") && <span className="ki-badge">KI-Vorschlag</span>}
        {s.problems.length > 0 && s.status !== "approved" && (
          <span className="warn-note">{s.problems.length} offen</span>
        )}
        <span className={`sec-status sec-${s.status}`}>{STATUS_LABEL[s.status]}</span>
      </div>
      {open && (
        <div className="section-body">
          {(s.kind === "basis" || s.kind === "questions") && (
            <p className="muted small">
              Die Software stellt nur die belegte Aktenlage zusammen. Die Beurteilung und die
              Antworten formulieren Sie selbst.
            </p>
          )}
          {s.problems.length > 0 && (
            <ul className="problems">
              {s.problems.map((p) => <li key={p} className="warn-note">{p}</li>)}
            </ul>
          )}
          {s.style.length > 0 && (
            <ul className="style-hints">
              {s.style.map((h, i) => (
                <li key={i}><strong>{h.text}</strong> – {h.hint}</li>
              ))}
            </ul>
          )}
          <textarea
            className="section-text"
            value={text}
            rows={Math.min(24, Math.max(6, text.split("\n").length + 2))}
            onChange={(e) => setText(e.target.value)}
            disabled={s.status === "approved"}
          />
          <div className="row">
            {s.status === "approved" ? (
              <button onClick={() => save("draft")}>Freigabe aufheben</button>
            ) : (
              <>
                <button disabled={!dirty} onClick={() => save()}>Speichern</button>
                <button onClick={() => save("reviewed")}>Als geprüft markieren</button>
                {s.content_md.includes("⟦KI⟧") && (
                  <button onClick={async () => {
                    await api.acceptProposals(caseId, s.section_key);
                    onChanged();
                  }}>KI-Vorschläge geprüft übernehmen</button>
                )}
                <button className="primary" onClick={() => save("approved")}>Freigeben</button>
              </>
            )}
            <span className="grow" />
            {s.model_id && <span className="muted small">Modell: {s.model_id}</span>}
          </div>
          {msg && <p className="warn-note">{msg}</p>}
        </div>
      )}
    </li>
  );
}

export default function GutachtenTab({ caseId }: { caseId: string }) {
  const [drafts, setDrafts] = useState<DraftSection[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [saved, setSaved] = useState("");
  const load = () => {
    api.getDrafts(caseId).then(setDrafts);
    api.listQuestions(caseId).then(setQuestions);
  };
  useEffect(load, [caseId]);

  const approved = drafts.filter((d) => d.status === "approved").length;
  const allDone = drafts.length > 0 && approved === drafts.length;

  return (
    <div className="tab-body">
      <div className="panel">
        <h3>Gutachten-Entwurf</h3>
        <AnalysisBar
          caseId={caseId}
          steps={["vorentwurf"]}
          label="KI-Vorentwurf erstellen"
          onDone={load}
          describe={(r) => `${r.vorentwurf?.proposals ?? 0} KI-Vorschläge eingesetzt, markiert und vor der ` +
            "Freigabe zu prüfen. Befragung und Befund werden nicht erzeugt."}
        />
        <AnalysisBar
          caseId={caseId}
          steps={["draft"]}
          label={drafts.length ? "Entwurf aktualisieren" : "Entwurf erstellen"}
          onDone={load}
          describe={(r) =>
            `${r.draft?.generated.length ?? 0} Abschnitte erstellt` +
            (r.draft?.skipped.length ? `, ${r.draft.skipped.length} unverändert (freigegeben oder von Ihnen bearbeitet)` : "") +
            (r.draft?.failed.length ? `, ${r.draft.failed.length} fehlgeschlagen` : "") +
            "."
          }
        />
        <p className="muted small">
          Abschnittsweise nach Vorlage. Jeder Satz aus der Akte trägt seine Fundstelle; Stellen
          mit {"⚠"} sind nicht belegt und müssen bereinigt werden. Freigegebene Abschnitte und
          Eigene Texte bleiben bei einer Aktualisierung erhalten.
          {questions.length > 0 && ` Beweisfragen: ${questions.length}.`}
        </p>
        {drafts.length > 0 && (
          <div className="row">
            <span>
              <strong>{approved}</strong> von {drafts.length} Abschnitten freigegeben
            </span>
            <span className="grow" />
            <button className="primary" onClick={() => downloadFile(api.exportUrl(caseId))
              .then((p) => setSaved(p ? `Gespeichert: ${p}` : ""))
              .catch((e) => setSaved(`Export fehlgeschlagen: ${errorText(e)}`))}>
              {allDone ? "Word exportieren" : "Entwurf als Word exportieren"}
            </button>
          </div>
        )}
        {saved && <p className="notice small">{saved}</p>}
      </div>
      <ul className="sections">
        {drafts.map((d) => (
          <Section key={d.section_key} caseId={caseId} s={d} onChanged={load} />
        ))}
      </ul>
    </div>
  );
}
