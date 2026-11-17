// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { api, errorText, Finding } from "../api";
import type { OpenPage } from "../pages/CaseView";
import AnalysisBar from "./AnalysisBar";
import CiteLinks from "./CiteLinks";

const TYPE_LABEL: Record<string, string> = {
  identity_mismatch: "Personalien",
  predates_accident: "Vorbefund",
  causality_conflict: "Kausalität",
  laterality_conflict: "Seitenangabe",
  date_contradiction: "Datum",
  implausible_date: "Datum",
  coverage_gap: "Behandlungslücke",
  ki_widerspruch: "Inhaltlicher Widerspruch",
  ki_vorschaden_abgrenzung: "Abgrenzung Vorschaden",
  ki_zwischenverlauf: "Unklarer Zwischenverlauf",
  ki_kausalkette: "Kausalkette",
  ki_fehlende_unterlage: "Fehlende Unterlage",
  ki_spaete_meldung: "Späte Meldung / Latenz",
};
const SEVERITY_LABEL = { high: "wichtig", medium: "prüfen", low: "Hinweis" };

export default function HinweiseTab({
  caseId,
  openPage,
  onChanged,
}: {
  caseId: string;
  openPage: OpenPage;
  onChanged: () => void;
}) {
  const [items, setItems] = useState<Finding[]>([]);
  const [showDone, setShowDone] = useState(false);
  const [msg, setMsg] = useState("");
  const load = () => api.getFindings(caseId).then(setItems);
  useEffect(() => {
    load();
  }, [caseId]);

  const decide = async (f: Finding, status: string) => {
    await api.decideFinding(caseId, f.id, status);
    load();
    onChanged();
  };
  const exclude = async (f: Finding) => {
    if (f.document_id == null) return;
    try {
      await api.excludeDocument(caseId, f.document_id, true);
      await api.decideFinding(caseId, f.id, "accepted").catch(() => undefined);
      setMsg("Dokument ausgeschlossen – Aktenauszug und Prüfung wurden neu erstellt.");
    } catch (e) {
      setMsg(errorText(e));
    }
    load();
    onChanged();
  };

  const open = items.filter((f) => f.status === "open");
  const done = items.filter((f) => f.status !== "open");

  const card = (f: Finding) => (
    <li key={f.id} className={`finding sev-${f.severity} st-${f.status}`}>
      <div className="finding-head">
        <span className={`sev-pill sev-${f.severity}`}>{SEVERITY_LABEL[f.severity]}</span>
        <span className="finding-type">{TYPE_LABEL[f.type] ?? f.type}</span>
        {f.created_by === "ki" && (
          <span className="badge b-ki" title="vom Sprachmodell gefunden – Fundstellen und
            Daten geprüft, Inhalt bitte an der Akte verifizieren">KI</span>
        )}
        <span className="grow" />
        {f.status !== "open" && (
          <span className="muted small">
            {f.status === "accepted" ? "bestätigt" : "verworfen"}
          </span>
        )}
      </div>
      <div className="finding-claim">{f.claim}</div>
      {f.explanation && <div className="muted small">{f.explanation}</div>}
      <div className="finding-foot">
        <span className="muted small">Fundstellen:</span>
        <CiteLinks
          citations={[f.source_a, f.source_b].filter((c) => c != null)}
          openPage={openPage}
        />
        <span className="grow" />
        {f.status === "open" ? (
          <>
            {f.type === "identity_mismatch" && f.severity === "high" && f.document_id != null && (
              <button onClick={() => exclude(f)}>Dokument ausschliessen</button>
            )}
            <button onClick={() => decide(f, "accepted")}>Bestätigen</button>
            <button className="link" onClick={() => decide(f, "rejected")}>Verwerfen</button>
          </>
        ) : (
          <button className="link" onClick={() => decide(f, "open")}>Wieder öffnen</button>
        )}
      </div>
    </li>
  );

  return (
    <div className="tab-body">
      <div className="panel">
        <h3>Hinweise und Widersprüche</h3>
        <AnalysisBar
          caseId={caseId}
          steps={["checks", "checks_ki"]}
          label="Prüfung erneut ausführen"
          onDone={() => {
            load();
            onChanged();
          }}
          describe={(r) =>
            `${r.checks?.findings ?? 0} Hinweise aus den Regeln, ` +
            `${r.checks_ki?.findings ?? 0} aus der KI-Prüfung.`}
        />
        {msg && <p className="notice">{msg}</p>}
        <p className="muted small">
          Regeln prüfen Personalien, Vorbefunde vor dem Unfall, Seitenangaben,
          Kausalitätsmarkierungen, Daten und Behandlungslücken. Die KI-Prüfung (markiert „KI“)
          sucht zusätzlich inhaltliche Widersprüche, offene Vorschaden-Abgrenzungen, unklare
          Zwischenverläufe, Kausalketten, fehlende Unterlagen und späte Meldungen, jeweils mit
          geprüften Fundstellen und ohne Wertung. Entscheidungen
          bleiben bei erneuter Auswertung erhalten.
        </p>
        {open.length === 0 && (
          <p className="muted">Keine offenen Hinweise.</p>
        )}
        <ul className="findings">{open.map(card)}</ul>
        {done.length > 0 && (
          <>
            <button className="link-btn" onClick={() => setShowDone(!showDone)}>
              {showDone ? "Erledigte ausblenden" : `Erledigte anzeigen (${done.length})`}
            </button>
            {showDone && <ul className="findings">{done.map(card)}</ul>}
          </>
        )}
      </div>
    </div>
  );
}
