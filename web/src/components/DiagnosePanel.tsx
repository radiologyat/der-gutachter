// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { api, Diagnostics, errorText, STEP_LABEL } from "../api";

const STAGE: Record<string, string> = {
  page_analysis: "Registrierung (je Seite)",
  fact_extract: "Extraktion (je Abschnitt)",
  cover: "Gutachtenauftrag",
  checks_ki: "KI-Prüfung",
  draft_basis: "Entwurf: Entscheidungsgrundlage",
  draft_narrative: "Entwurf: Text",
  vorentwurf: "KI-Vorentwurf: Text",
  vorentwurf_antwort: "KI-Vorentwurf: Antworten",
};

const BUILD: Record<string, string> = {
  cuda: "NVIDIA CUDA", vulkan: "Grafikkarte (Vulkan)", cpu: "nur Prozessor (langsam)",
  metal: "Apple Metal",
};

/** Where did the information go? Counts per stage, from pages to statements. */
export default function DiagnosePanel({ caseId }: { caseId: string }) {
  const [d, setD] = useState<Diagnostics | null>(null);
  const [err, setErr] = useState("");
  const load = () => api.diagnostics(caseId).then(setD).catch((e) => setErr(errorText(e)));
  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [caseId]);

  if (err) return <p className="warn-note">{err}</p>;
  if (!d) return null;
  const b = d.llm_backend;
  return (
    <div className="panel">
      <h3>Diagnose: was jede Stufe ergeben hat</h3>
      <ul className="small">
        {d.hints.map((h, i) => <li key={i}>{h}</li>)}
      </ul>
      <div className="diag-grid">
        <div className="diag-card">
          <h4>1. Texterkennung</h4>
          <div className="big">{d.ocr.done} / {d.ocr.pages} Seiten</div>
          <div className="small muted">
            ohne verwertbaren Text: {d.ocr.no_text}
            {d.ocr.no_text_pages.length > 0 && ` (Bl. ${d.ocr.no_text_pages.join(", ")}`
              + (d.ocr.no_text > d.ocr.no_text_pages.length ? " …)" : ")")}
            <br />zu prüfen: {d.ocr.review} · Dubletten: {d.ocr.duplicates} · Ø {d.ocr.avg_chars}
            {" "}Zeichen/Seite
            <br />Verfahren: {Object.entries(d.ocr.engines).map(([k, v]) => `${k} ${v}`)
              .join(", ")}
          </div>
        </div>
        <div className="diag-card">
          <h4>2. Register</h4>
          <div className="big">{d.documents.count} Dokumente</div>
          <div className="small muted">
            ausgeschlossen: {d.documents.excluded} · grösstes: {d.documents.largest_pages} Seiten
          </div>
        </div>
        <div className="diag-card">
          <h4>3. Extraktion</h4>
          <div className="big">{d.extraction.verified} belegt</div>
          <div className="small muted">
            von {d.extraction.statements} gefundenen Angaben · verworfen {d.extraction.rejected}
            {Object.keys(d.extraction.reject_reasons).length > 0 && (
              <> ({Object.entries(d.extraction.reject_reasons).map(([k, v]) => `${k}: ${v}`)
                .join("; ")})</>
            )}
            <br />Dokumente ohne Angabe: {d.extraction.documents_without_statements}
          </div>
        </div>
        <div className="diag-card">
          <h4>4. Ergebnis</h4>
          <div className="big">{d.aktenauszug} Einträge</div>
          <div className="small muted">im Aktenauszug · {d.findings} Hinweise</div>
        </div>
        <div className="diag-card">
          <h4>Sprachmodell</h4>
          <div className="big">{b ? BUILD[b.build] ?? b.build : "nicht gestartet"}</div>
          <div className="small muted">
            {b?.device ?? ""}
            {b?.gpu_layers ? ` · ${b.gpu_layers} Schichten auf der Grafikkarte` : ""}
            {b && !b.on_gpu && " · läuft ohne Grafikkarte"}
          </div>
        </div>
      </div>
      <table className="cases small">
        <thead>
          <tr><th>Modellanfragen</th><th>erfolgreich</th><th>aus Speicher</th><th>Fehler</th>
            <th>Ø Dauer</th><th>längste</th></tr>
        </thead>
        <tbody>
          {Object.entries(d.model_calls).map(([k, v]) => (
            <tr key={k}>
              <td>{STAGE[k] ?? STEP_LABEL[k] ?? k}</td><td>{v.ok}</td><td>{v.cache}</td>
              <td className={v.error ? "warn-note" : ""}>{v.error}</td>
              <td>{v.avg_s != null ? `${v.avg_s} s` : "—"}</td>
              <td>{v.max_s != null ? `${v.max_s} s` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {d.model_errors.length > 0 && (
        <>
          <h4 className="small">Fehlgeschlagene Modellanfragen (letzte)</h4>
          <ul className="small">
            {d.model_errors.map((e, i) => (
              <li key={i}>{STAGE[e.stage] ?? e.stage} · {e.ref}: {e.error}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
