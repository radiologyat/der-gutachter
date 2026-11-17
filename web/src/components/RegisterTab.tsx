// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { api, DOC_TYPE_LABEL, IndexRow } from "../api";
import type { OpenPage } from "../pages/CaseView";
import AnalysisBar from "./AnalysisBar";

const REASON_LABEL: Record<string, string> = {
  source: "neue Datei",
  page_marker: "Seitenangabe",
  llm: "Inhalt",
  fallback: "nicht erkannt",
};

export default function RegisterTab({
  caseId,
  onChanged,
  openPage,
}: {
  caseId: string;
  onChanged: () => void;
  openPage: OpenPage;
}) {
  const [rows, setRows] = useState<IndexRow[]>([]);
  const load = () => api.getIndex(caseId).then(setRows);
  useEffect(() => {
    load();
  }, [caseId]);

  const segmented = rows.some((r) => r.doc_type !== undefined);

  return (
    <div className="tab-body">
      <div className="panel">
        <h3>Aktenregister</h3>
        <AnalysisBar
          caseId={caseId}
          steps={["index", "extract", "timeline", "checks"]}
          label={segmented ? "Neu auswerten" : "Akte auswerten"}
          onDone={() => {
            load();
            onChanged();
          }}
          describe={(r) =>
            `${r.index?.documents ?? 0} Dokumente registriert, ` +
            `${r.extract?.verified ?? 0} belegte Angaben` +
            (r.extract?.unverified ? ` (${r.extract.unverified} unbelegt)` : "") +
            `, ${r.timeline?.entries ?? 0} Einträge im Aktenauszug` +
            (r.checks?.findings ? `, ${r.checks.findings} Hinweise zur Prüfung.` : ".")
          }
        />
        {!segmented && rows.length > 0 && (
          <p className="muted">
            Noch nicht registriert – die Tabelle zeigt die importierten Dateien.
            „Akte auswerten“ erkennt Dokumente (Typ, Datum, Autor) und extrahiert die
            Angaben für den Aktenauszug. Eine erneute Auswertung ersetzt Register und
            extrahierte Angaben.
          </p>
        )}
        {rows.length === 0 && (
          <p className="muted">Noch keine Akte importiert (Reiter „Akte“).</p>
        )}
        {rows.length > 0 && (
          <table className="cases">
            <thead>
              <tr>
                <th>Blatt</th>
                <th>Typ</th>
                <th>Dokument</th>
                <th>Datum</th>
                <th>Autor / Institution</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} onClick={() => openPage(r.start_seq)}>
                  <td>
                    {r.start_seq}
                    {r.end_seq !== r.start_seq ? `–${r.end_seq}` : ""} d. A.
                  </td>
                  <td>{r.doc_type ? (DOC_TYPE_LABEL[r.doc_type] ?? r.doc_type) : "—"}</td>
                  <td>
                    <div className="case-title">{r.title ?? r.name ?? "—"}</div>
                    {r.verify_note && <div className="warn-note">{r.verify_note}</div>}
                    {r.boundary_reason && (
                      <div className="muted small">
                        Grenze: {REASON_LABEL[r.boundary_reason] ?? r.boundary_reason}
                      </div>
                    )}
                  </td>
                  <td>{r.doc_date ?? "—"}</td>
                  <td className="muted">
                    {[r.author, r.institution].filter(Boolean).join(" · ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
