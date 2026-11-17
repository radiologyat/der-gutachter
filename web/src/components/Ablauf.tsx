// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { AnalysisResult, api, CaseSummary, errorText, Job, Suggestion } from "../api";

const FIELD: Record<string, string> = {
  auftraggeber: "Auftraggeber", aktenzeichen: "Aktenzeichen", patient_name: "Name",
  patient_dob: "Geburtsdatum", accident_date: "Unfalldatum",
};

function label(s: Suggestion): string {
  const p = s.payload;
  if (s.kind === "case_field") return `${FIELD[p.field] ?? p.field}: ${p.value}`;
  if (s.kind === "date") return `${p.kind === "frist" ? "Frist" : "Termin"} ${p.date}`;
  return `Frage: ${p.text}`;
}

/** Guided next steps for a case: what is done, what is next – one button each. */
export default function Ablauf({ case_, onChanged }: {
  case_: CaseSummary;
  onChanged: () => void;
}) {
  const [job, setJob] = useState<Job<AnalysisResult> | null>(null);
  const [openSugg, setOpenSugg] = useState(0);
  const [verifiedSugg, setVerifiedSugg] = useState(0);
  const [autoApplied, setAutoApplied] = useState<Suggestion[]>([]);
  const [msg, setMsg] = useState("");
  const st = case_.stats;

  const loadSugg = () =>
    api.getSuggestions(case_.id).then((s) => {
      const open = s.filter((x) => x.status === "open");
      setOpenSugg(open.length);
      setVerifiedSugg(open.filter((x) => x.verified).length);
      setAutoApplied(s.filter((x) => x.status === "accepted" && x.auto));
    });

  const follow = async (jobId: string) => {
    for (;;) {
      const j = await api.getJob<AnalysisResult>(jobId);
      setJob(j);
      if (j.status !== "running") {
        setJob(null);
        if (j.status === "error") setMsg(`Fehler: ${j.error}`);
        loadSugg();
        onChanged();
        return;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
  };

  useEffect(() => {
    loadSugg();
    // pick up a running intake/analysis started from the landing page (read-only)
    api.runningJob(case_.id).then((r) => { if (r.job_id) follow(r.job_id); });
  }, [case_.id]);

  const run = async (fn: () => Promise<{ job_id: string }>) => {
    setMsg("");
    try {
      const { job_id } = await fn();
      follow(job_id);
    } catch (e) {
      setMsg(errorText(e));
    }
  };

  const digitized = (st?.pages ?? 0) > 0 && (st?.pending ?? 0) === 0;

  return (
    <div className="panel span-all ablauf">
      <h3>Angaben aus dem Gutachtenauftrag</h3>
      <p className="muted small">
        Die ersten Seiten der Akte (Auftrag, Beweisbeschluss) werden zuerst gelesen:
        Auftraggeber, Personalien, Ereignisdatum, Fristen und Beweisfragen. Angaben, deren
        Wortlaut in der Akte gefunden wurde, werden übernommen und sind unten einzeln
        rückgängig zu machen; die übrigen warten auf Bestätigung.
      </p>
      {job && <p className="muted small">Auswertung läuft – Stand siehe Anzeige oben.</p>}
      {!job && <CoverPages case_={case_} onStarted={(id) => follow(id)} />}
      {!job && openSugg > 0 && (
        <div className="row">
          <span>{openSugg} Angabe(n) – Bestätigung ausstehend (Liste unten)</span>
          {digitized && verifiedSugg > 0 && (
            <button className="primary" onClick={async () => {
              await api.acceptVerified(case_.id);
              loadSugg();
              onChanged();
            }}>
              {verifiedSugg} belegte Angaben übernehmen
            </button>
          )}
        </div>
      )}
      {!job && !digitized && (st?.pages ?? 0) > 0 && (
        <div className="row">
          <span>Texterkennung noch nicht abgeschlossen.</span>
          <button className="primary" onClick={() => run(() => api.intake(case_.id))}>
            Akte vollständig verarbeiten
          </button>
        </div>
      )}
      {autoApplied.length > 0 && (
        <details className="auto-applied" open={!job}>
          <summary>
            {autoApplied.length} Angaben automatisch übernommen (belegt) – zur Kontrolle
          </summary>
          <ul className="suggestions">
            {autoApplied.map((s) => (
              <li key={s.id}>
                <span className="grow">{label(s)}</span>
                <button className="link" onClick={async () => {
                  await api.undoSuggestion(case_.id, s.id);
                  loadSugg();
                  onChanged();
                }}>Rückgängig</button>
              </li>
            ))}
          </ul>
        </details>
      )}
      {msg && <p className="warn-note">{msg}</p>}
    </div>
  );
}


/** Where the assignment was read from — and a way to point at the right pages when the
 *  automatic choice was wrong (e.g. the assignment is not the first file). */
function CoverPages({ case_, onStarted }: { case_: CaseSummary;
                                            onStarted: (jobId: string) => void }) {
  const read = case_.cover_pages_read;
  const [edit, setEdit] = useState(false);
  const [from, setFrom] = useState(read ? String(read[0]) : "1");
  const [to, setTo] = useState(read ? String(read[1]) : "3");
  const [err, setErr] = useState("");
  return (
    <div className="small cover-pages">
      {read ? <span>Gelesen von Blatt {read[0]}–{read[1]}. </span>
        : <span>Der Auftrag wurde noch nicht gelesen. </span>}
      {!edit ? (
        <button className="link-btn" onClick={() => setEdit(true)}>
          {read ? "Falsche Seiten? Auftrag selbst angeben" : "Auftrag selbst angeben"}
        </button>
      ) : (
        <span className="row inline">
          Auftrag liegt auf Blatt
          <input className="num" value={from} onChange={(e) => setFrom(e.target.value)} />
          bis
          <input className="num" value={to} onChange={(e) => setTo(e.target.value)} />
          <button className="primary" onClick={async () => {
            setErr("");
            try {
              const r = await api.readCoverPages(case_.id, +from, +to);
              setEdit(false);
              onStarted(r.job_id);
            } catch (e) {
              setErr(errorText(e));
            }
          }}>Auftrag neu lesen</button>
          <button onClick={() => setEdit(false)}>Abbrechen</button>
        </span>
      )}
      {err && <span className="warn-note"> {err}</span>}
    </div>
  );
}
