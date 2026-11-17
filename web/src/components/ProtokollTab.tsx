// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useMemo, useState } from "react";
import { api, downloadFile, errorText, ProtocolRow } from "../api";
import DiagnosePanel from "./DiagnosePanel";

type Who = "alle" | "Sachverständige/r" | "Programm" | "KI-Modell";

/** Everything that happened in the case: who (expert, program, model), when, what.
 *  Exportable as CSV, e.g. as an attachment documenting the use of AI. */
export default function ProtokollTab({ caseId }: { caseId: string }) {
  const [rows, setRows] = useState<ProtocolRow[]>([]);
  const [who, setWho] = useState<Who>("alle");
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api.getProtocol(caseId).then(setRows).catch((e) => setErr(errorText(e)));
  }, [caseId]);

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return rows
      .filter((r) => who === "alle" || r.wer === who)
      .filter((r) => !t || `${r.aktion} ${r.detail}`.toLowerCase().includes(t))
      .slice()
      .reverse();
  }, [rows, who, q]);
  const count = (w: Who) => rows.filter((r) => r.wer === w).length;

  return (
    <div className="tab-body">
      <DiagnosePanel caseId={caseId} />
      <div className="panel">
        <div className="panel-head">
          <h3>Protokoll</h3>
          <div className="actions">
            <select value={who} onChange={(e) => setWho(e.target.value as Who)}>
              <option value="alle">alle ({rows.length})</option>
              <option value="Sachverständige/r">Sachverständige/r ({count("Sachverständige/r")})
              </option>
              <option value="Programm">Programm ({count("Programm")})</option>
              <option value="KI-Modell">KI-Modell ({count("KI-Modell")})</option>
            </select>
            <input placeholder="Suchen …" value={q} onChange={(e) => setQ(e.target.value)} />
            <button onClick={() => downloadFile(api.protocolCsv(caseId))
              .then((p) => p && setErr(`Gespeichert: ${p}`))
              .catch((e) => setErr(errorText(e)))}>
              Als CSV exportieren
            </button>
          </div>
        </div>
        <p className="muted small">
          Lückenlose Spur des Falls: Import, Texterkennung, jede Modellanfrage (Modell und
          Vorlagen-Version), verworfene KI-Sätze mit Grund, jede manuelle Korrektur und
          Freigabe. Neueste zuerst.
        </p>
        {err && <p className="warn-note">{err}</p>}
        <table className="cases protocol">
          <thead>
            <tr>
              <th>Zeit (UTC)</th>
              <th>Wer</th>
              <th>Aktion</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i}>
                <td className="nowrap small">{(r.ts ?? "").slice(0, 19)}</td>
                <td className="nowrap">
                  <span className={`badge ${r.wer === "Sachverständige/r" ? "b-manual"
                    : r.wer === "KI-Modell" ? "b-ki" : "b-auto"}`}>{r.wer}</span>
                </td>
                <td className="nowrap">{r.aktion}</td>
                <td className="small">{r.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
