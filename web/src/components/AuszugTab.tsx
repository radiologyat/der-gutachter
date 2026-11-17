// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useMemo, useState } from "react";
import {
  api,
  CATEGORY_LABEL,
  CAUSALITY_LABEL,
  errorText,
  Fact,
  TimelineEdit,
  TimelineRow,
} from "../api";
import type { OpenPage } from "../pages/CaseView";
import CiteLinks from "./CiteLinks";

const LAT: Record<string, string> = { links: "li.", rechts: "re.", beidseits: "bds." };
type Filter = "alle" | "ungeprueft" | "manuell" | "ausgeschlossen";

/** Provenance of a row: from the Akte (program), corrected or added by the expert. */
function Origin({ r }: { r: TimelineRow }) {
  if (r.created_by !== "pipeline")
    return <span className="badge b-manual" title="manuell ergänzt">✋ manuell</span>;
  if (r.edited && r.original_json)
    return <span className="badge b-edited" title="vom Programm erkannt, manuell korrigiert">
      ✎ korrigiert</span>;
  return <span className="badge b-auto" title="vom Programm aus der Akte erkannt, Zitat und
    Datum geprüft">Akte</span>;
}

const deIn = (iso: string | null) =>
  iso ? iso.slice(0, 10).split("-").reverse().join(".") : "";

function Editor({
  init,
  onSave,
  onCancel,
  withSource,
}: {
  init: TimelineEdit;
  onSave: (v: TimelineEdit) => Promise<void>;
  onCancel: () => void;
  withSource?: boolean;
}) {
  const [v, setV] = useState<TimelineEdit>(init);
  const [err, setErr] = useState("");
  const set = (k: keyof TimelineEdit, x: string) =>
    setV((o) => ({ ...o, [k]: x === "" ? null : x }));
  return (
    <div className="auszug-edit">
      <div className="row-fields">
        <label>
          Datum
          <input value={v.entry_date ?? ""} placeholder="TT.MM.JJJJ"
            onChange={(e) => set("entry_date", e.target.value)} />
        </label>
        <label>
          bis
          <input value={v.date_end ?? ""} placeholder="optional"
            onChange={(e) => set("date_end", e.target.value)} />
        </label>
        <label>
          Kategorie
          <select value={v.category ?? ""} onChange={(e) => set("category", e.target.value)}>
            <option value="">—</option>
            {Object.entries(CATEGORY_LABEL).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </select>
        </label>
        <label>
          Kausalität
          <select value={v.causality ?? ""} onChange={(e) => set("causality", e.target.value)}>
            <option value="">—</option>
            {Object.entries(CAUSALITY_LABEL).filter(([k]) => k !== "none").map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </select>
        </label>
        <label>
          Seite
          <select value={v.laterality ?? ""} onChange={(e) => set("laterality", e.target.value)}>
            <option value="">—</option>
            <option value="links">links</option>
            <option value="rechts">rechts</option>
            <option value="beidseits">beidseits</option>
          </select>
        </label>
      </div>
      <label className="wide">
        Ereignis
        <input value={v.title ?? ""} onChange={(e) => set("title", e.target.value)} />
      </label>
      <label className="wide">
        Details
        <textarea rows={2} value={v.summary ?? ""}
          onChange={(e) => set("summary", e.target.value)} />
      </label>
      {withSource && (
        <div className="row-fields">
          <label>
            Fundstelle Bl.
            <input type="number" min={1} value={v.seq ?? ""} placeholder="optional"
              onChange={(e) => setV((o) => ({ ...o, seq: e.target.value ? +e.target.value
                : null }))} />
          </label>
          <label className="wide">
            Zitat
            <input value={v.quote ?? ""} placeholder="optional"
              onChange={(e) => set("quote", e.target.value)} />
          </label>
        </div>
      )}
      {err && <p className="warn-note">{err}</p>}
      <div className="actions">
        <button className="primary" onClick={() => onSave(v).catch((e) =>
          setErr(errorText(e)))}>Speichern</button>
        <button onClick={onCancel}>Abbrechen</button>
      </div>
    </div>
  );
}

export default function AuszugTab({
  caseId,
  openPage,
  onChanged,
}: {
  caseId: string;
  openPage: OpenPage;
  onChanged?: () => void;
}) {
  const [rows, setRows] = useState<TimelineRow[]>([]);
  const [unbelegt, setUnbelegt] = useState<Fact[]>([]);
  const [showUnbelegt, setShowUnbelegt] = useState(false);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [filter, setFilter] = useState<Filter>("alle");
  const [err, setErr] = useState("");

  const load = () => {
    api.getTimeline(caseId).then(setRows).catch((e) => setErr(errorText(e)));
    api.getFacts(caseId, false).then(setUnbelegt).catch(() => undefined);
  };
  useEffect(load, [caseId]);
  const changed = () => {
    load();
    onChanged?.();
  };
  const act = (p: Promise<unknown>) => p.then(changed).catch((e) => setErr(errorText(e)));

  const shown = useMemo(() => rows.filter((r) =>
    filter === "ungeprueft" ? !r.reviewed && !r.excluded
      : filter === "manuell" ? r.created_by !== "pipeline" || !!r.edited
        : filter === "ausgeschlossen" ? !!r.excluded : true), [rows, filter]);
  const open = rows.filter((r) => !r.reviewed && !r.excluded).length;

  return (
    <div className="tab-body">
      <div className="panel">
        <div className="panel-head">
          <h3>Aktenauszug (chronologisch)</h3>
          <div className="actions">
            <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
              <option value="alle">alle ({rows.length})</option>
              <option value="ungeprueft">ungeprüft ({open})</option>
              <option value="manuell">manuell / korrigiert</option>
              <option value="ausgeschlossen">ausgeschlossen</option>
            </select>
            {open > 0 && (
              <button onClick={() => act(api.reviewAllTimeline(caseId))}>
                Alle als geprüft markieren
              </button>
            )}
            <button className="primary" onClick={() => setEditing("new")}>+ Eintrag</button>
          </div>
        </div>
        <p className="muted small">
          Jede Zeile zeigt ihre Herkunft. Korrekturen behalten das Original (wiederherstellbar);
          Einträge aus der Akte werden ausgeschlossen statt gelöscht. Nach Änderungen werden
          Hinweise und Gutachten als „veraltet“ markiert (oben „Alles aktualisieren“).
        </p>
        {err && <p className="warn-note">{err}</p>}
        {editing === "new" && (
          <Editor withSource init={{}} onCancel={() => setEditing(null)}
            onSave={async (v) => {
              await api.addTimeline(caseId, v);
              setEditing(null);
              changed();
            }} />
        )}
        {rows.length === 0 && editing !== "new" && (
          <p className="muted">
            Wird über „Akte auswerten“ (Reiter „Register“) erzeugt oder manuell mit
            „+ Eintrag“ ergänzt. Automatisch nur Angaben, deren Zitat und Datum in der Akte
            gefunden wurden.
          </p>
        )}
        {shown.length > 0 && (
          <table className="cases auszug">
            <thead>
              <tr>
                <th>✓</th>
                <th>Datum</th>
                <th>Kategorie</th>
                <th>Ereignis</th>
                <th>Kausalität</th>
                <th>Fundstelle</th>
                <th>Herkunft</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) =>
                editing === r.id ? (
                  <tr key={r.id}>
                    <td colSpan={8}>
                      <Editor onCancel={() => setEditing(null)}
                        init={{ entry_date: deIn(r.entry_date), date_end: deIn(r.date_end),
                          category: r.category, causality: r.causality,
                          laterality: r.laterality, title: r.title, summary: r.summary }}
                        onSave={async (v) => {
                          await api.updateTimeline(caseId, r.id, v);
                          setEditing(null);
                          changed();
                        }} />
                    </td>
                  </tr>
                ) : (
                  <tr key={r.id} className={`caus-${r.causality ?? "none"} ${r.excluded
                    ? "excluded" : ""}`}>
                    <td>
                      <input type="checkbox" checked={!!r.reviewed} disabled={!!r.excluded}
                        title="geprüft"
                        onChange={(e) => act(api.flagTimeline(caseId, r.id, "reviewed",
                          e.target.checked))} />
                    </td>
                    <td className="nowrap">
                      {r.entry_date}
                      {r.date_end ? ` – ${r.date_end}` : ""}
                    </td>
                    <td>{CATEGORY_LABEL[r.category ?? ""] ?? r.category ?? "—"}</td>
                    <td>
                      <div className="case-title">
                        {r.title}
                        {r.laterality && LAT[r.laterality] ? ` (${LAT[r.laterality]})` : ""}
                      </div>
                      {r.summary && r.summary !== r.title && (
                        <div className="muted">{r.summary}</div>
                      )}
                      {r.excluded ? <div className="small warn-note">ausgeschlossen – wird
                        im Gutachten nicht verwendet</div> : null}
                    </td>
                    <td>{CAUSALITY_LABEL[r.causality ?? ""] ?? r.causality ?? "—"}</td>
                    <td>
                      {r.citations.length ? (
                        <CiteLinks citations={r.citations} openPage={openPage} />
                      ) : (
                        <span className="muted small">ohne Beleg (manuell)</span>
                      )}
                    </td>
                    <td><Origin r={r} /></td>
                    <td className="nowrap row-actions">
                      <button className="link-btn" onClick={() => setEditing(r.id)}>
                        bearbeiten</button>
                      {r.original_json && r.created_by === "pipeline" && !!r.edited && (
                        <button className="link-btn" title="Version aus der Akte
                          wiederherstellen" onClick={() =>
                          act(api.restoreTimeline(caseId, r.id))}>Original</button>
                      )}
                      {r.created_by === "pipeline" ? (
                        <button className="link-btn" onClick={() => act(api.flagTimeline(
                          caseId, r.id, "exclude", !r.excluded))}>
                          {r.excluded ? "einschliessen" : "ausschliessen"}</button>
                      ) : (
                        <button className="link-btn" onClick={() =>
                          confirm("Manuellen Eintrag löschen?") &&
                          act(api.deleteTimeline(caseId, r.id))}>löschen</button>
                      )}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        )}
      </div>

      {unbelegt.length > 0 && (
        <div className="panel">
          <h3>
            Nicht belegte Angaben ({unbelegt.length}){" "}
            <button className="link-btn" onClick={() => setShowUnbelegt(!showUnbelegt)}>
              {showUnbelegt ? "ausblenden" : "anzeigen"}
            </button>
          </h3>
          <p className="muted small">
            Vom Modell vorgeschlagen, aber Zitat oder Datum nicht in der Akte gefunden —
            nicht im Aktenauszug. Bei Bedarf mit „+ Eintrag“ manuell übernehmen.
          </p>
          {showUnbelegt && (
            <table className="cases">
              <tbody>
                {unbelegt.map((f) => (
                  <tr key={f.id} onClick={() => openPage(f.global_seq, f.bbox)}>
                    <td className="nowrap">{f.fact_date ?? "—"}</td>
                    <td>
                      <div className="case-title">{f.title}</div>
                      <div className="muted small">„{f.quote}“</div>
                    </td>
                    <td className="warn-note">{f.verify_note}</td>
                    <td className="muted nowrap">Bl. {f.global_seq}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
