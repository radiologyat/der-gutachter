// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useMemo, useRef, useState } from "react";
import { api, CaseSummary, daysUntil, deDate, errorText, SystemInfo } from "../api";

export const STAGES = [
  ["intake", "Eingang"],
  ["ocr", "Digitalisiert"],
  ["index", "Registriert"],
  ["analysis", "Ausgewertet"],
  ["draft", "Entwurf"],
  ["done", "Fertig"],
] as const;

export const STAGE_LABEL: Record<string, string> = {
  intake: "Eingang / Digitalisierung",
  ocr: "Digitalisiert",
  index: "Registriert",
  analysis: "Ausgewertet",
  draft: "Entwurf",
  done: "Fertig",
};

const KIND_LABEL: Record<string, string> = {
  begutachtung: "Begutachtung",
  frist: "Frist",
  termin: "Termin",
  sonstiges: "Termin",
};

const JUR_LABEL: Record<string, string> = { CH: "Schweiz", AT: "Österreich", DE: "Deutschland" };

type Filter = "aktiv" | "fertig" | "alle";

function relative(days: number): string {
  if (days === 0) return "heute";
  if (days === 1) return "morgen";
  if (days === -1) return "gestern";
  return days > 0 ? `in ${days} Tagen` : `überfällig seit ${-days} Tagen`;
}

function urgency(days: number): "overdue" | "soon" | "" {
  if (days < 0) return "overdue";
  if (days <= 14) return "soon";
  return "";
}

function StageBar({ stage }: { stage: string }) {
  const idx = STAGES.findIndex(([k]) => k === stage);
  return (
    <div className="stagebar" title={STAGE_LABEL[stage] ?? stage}>
      <div className="steps">
        {STAGES.map(([k], i) => (
          <span key={k} className={i < idx ? "done" : i === idx ? "current" : ""} />
        ))}
      </div>
      <span className="stage-label">{STAGES[idx]?.[1] ?? stage}</span>
    </div>
  );
}

function NewCaseForm({ onCreated, onCancel }: {
  onCreated: (id: string) => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState("");
  const [jur, setJur] = useState("CH");
  const [date, setDate] = useState("");
  const [auftraggeber, setAuftraggeber] = useState("");
  const [err, setErr] = useState("");

  const create = async () => {
    if (!title.trim()) return;
    try {
      const c = await api.createCase({
        title: title.trim(),
        jurisdiction: jur,
        case_type: "unfall",
        accident_date: date || null,
        auftraggeber: auftraggeber.trim(),
      });
      onCreated(c.id);
    } catch (e) {
      setErr(errorText(e));
    }
  };

  return (
    <div className="panel new-case-form">
      <h3>Neuer Fall</h3>
      <div className="form-grid">
        <label className="span2">
          Fallbezeichnung
          <input
            autoFocus
            placeholder="Aktenzeichen oder Pseudonym, z. B. „CG230417 – Knie li.“"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && create()}
          />
        </label>
        <label>
          Jurisdiktion
          <select value={jur} onChange={(e) => setJur(e.target.value)}>
            <option value="CH">Schweiz</option>
            <option value="AT">Österreich</option>
            <option value="DE">Deutschland</option>
          </select>
        </label>
        <label>
          Unfalldatum
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label className="span2">
          Auftraggeber
          <input
            placeholder="Gericht oder Versicherung"
            value={auftraggeber}
            onChange={(e) => setAuftraggeber(e.target.value)}
          />
        </label>
      </div>
      <p className="muted small">
        Nur die Bezeichnung ist nötig. Auftraggeber, Daten, Fristen und Beweisfragen
        lassen sich später aus dem Gutachtenauftrag auslesen.
      </p>
      {err && <p className="warn-note">{err}</p>}
      <div className="row">
        <button className="primary" onClick={create} disabled={!title.trim()}>
          Fall anlegen
        </button>
        <button onClick={onCancel}>Abbrechen</button>
      </div>
    </div>
  );
}

function EmptyState({ onNew }: { onNew: () => void }) {
  return (
    <div className="empty-state">
      <h2>Willkommen</h2>
      <p className="muted">So entsteht ein Gutachten mit dem Gutachter:</p>
      <ol className="steps-intro">
        <li>
          <strong>Fall anlegen</strong>
          <span>Bezeichnung genügt, der Rest wird aus der Akte gelesen.</span>
        </li>
        <li>
          <strong>Akte-Ordner öffnen</strong>
          <span>Ordner mit Scans und PDFs wählen – Texterkennung, Gutachtenauftrag,
            Register, Aktenauszug, Prüfung und Entwurf entstehen in einem Durchgang.</span>
        </li>
        <li>
          <strong>Auswerten</strong>
          <span>Register, Aktenauszug und Beweisfragen, jede Angabe mit Fundstelle.</span>
        </li>
      </ol>
      <button onClick={onNew}>Leeren Fall anlegen</button>
    </div>
  );
}

function recall(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function remember(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private window: no memory, still works */
  }
}

export default function Dashboard({
  onOpen,
  onSetup,
}: {
  onOpen: (id: string) => void;
  onSetup: () => void;
}) {
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [sys, setSys] = useState<SystemInfo | null>(null);
  const [err, setErr] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("aktiv");
  const folderRef = useRef<HTMLInputElement>(null);
  const [opening, setOpening] = useState("");
  const [withDraft, setWithDraft] = useState(recall("gutachten.vorentwurf", "1") === "1");
  const [country, setCountry] = useState(recall("gutachten.country", "CH"));
  const [pending, setPending] = useState<{ name: string; files: File[] } | null>(null);

  const openFolder = async (files: FileList) => {
    const list = Array.from(files).filter(
      (f) => !f.name.startsWith(".") && !f.name.startsWith("~$") &&
        !["thumbs.db", "desktop.ini"].includes(f.name.toLowerCase()));
    if (!list.length) return;
    // import in name order: the assignment ("01_…") becomes Bl. 1 and is read first
    const relOf = (f: File) => (f as File & { webkitRelativePath?: string })
      .webkitRelativePath || f.name;
    list.sort((a, b) => relOf(a).localeCompare(relOf(b), "de", { numeric: true }));
    const rel = relOf(list[0]);
    setPending({ name: rel.split("/")[0] || "Neue Akte", files: list });
  };

  // step 2 of opening a folder: a short confirmation (country, KI-Vorentwurf)
  const startPending = async () => {
    if (!pending) return;
    const { name, files: list } = pending;
    setPending(null);
    remember("gutachten.country", country);
    remember("gutachten.vorentwurf", withDraft ? "1" : "0");
    try {
      setOpening(`„${name}“: Fall wird angelegt …`);
      const c = await api.createCase({ title: name, case_type: "unfall",
                                       jurisdiction: country });
      setOpening(`„${name}“: ${list.length} Dateien werden importiert …`);
      await api.upload(c.id, list);
      await api.intake(c.id, withDraft);  // the whole pipeline continues in the background
      onOpen(c.id);
    } catch (e) {
      setOpening(`Fehler: ${errorText(e)}`);
    }
  };

  useEffect(() => {
    // keep the list current while evaluations run in the background
    const t = setInterval(() => api.listCases().then(setCases).catch(() => undefined), 5000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    api.listCases().then(setCases).catch((e) => setErr(errorText(e)));
    api.system().then(setSys).catch(() => setSys(null));
  }, []);

  const all = cases ?? [];
  const active = all.filter((c) => c.stage !== "done");
  const deadlines = active
    .filter((c) => c.next_date)
    .map((c) => daysUntil(c.next_date!.date));
  const due = deadlines.filter((d) => d <= 14).length;
  const overdue = deadlines.filter((d) => d < 0).length;
  const review = all.reduce((a, c) => a + (c.stats?.review ?? 0), 0);
  const ready = all.filter((c) => c.stage === "ocr").length;

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return all
      .filter((c) =>
        filter === "alle" ? true : filter === "fertig" ? c.stage === "done" : c.stage !== "done",
      )
      .filter(
        (c) =>
          !q ||
          [c.title, c.auftraggeber, c.patient_ref].some((v) => v?.toLowerCase().includes(q)),
      )
      .sort((a, b) => (a.next_date?.date ?? "9999").localeCompare(b.next_date?.date ?? "9999"));
  }, [all, query, filter]);

  const today = new Date().toLocaleDateString("de-CH", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });

  return (
    <div className="dashboard">
      <div className="dash-head">
        <div>
          <h1>Arbeitsliste</h1>
          <p className="muted">{today}</p>
        </div>
        <div className="row">
          {!showNew && all.length > 0 && (
            <button onClick={() => setShowNew(true)}>+ Leerer Fall</button>
          )}
          <button className="primary" onClick={() => folderRef.current?.click()}>
            Akte-Ordner öffnen …
          </button>
          <input
            ref={folderRef}
            type="file"
            multiple
            style={{ display: "none" }}
            // @ts-expect-error non-standard attribute for folder selection
            webkitdirectory=""
            onChange={(e) => e.target.files && openFolder(e.target.files)}
          />
        </div>
      </div>

      {pending && (
        <div className="dialog-backdrop" onClick={() => setPending(null)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>Akte „{pending.name}“ öffnen</h3>
            <p className="muted small">{pending.files.length} Dateien. Die Auswertung läuft
              danach selbstständig; Sie können die App schliessen und später fortsetzen.</p>
            <fieldset>
              <legend>Land</legend>
              <label><input type="radio" checked={country === "CH"}
                onChange={() => setCountry("CH")} /> Schweiz</label>
              <label><input type="radio" checked={country === "AT"}
                onChange={() => setCountry("AT")} /> Österreich</label>
            </fieldset>
            <p className="muted small">Die Auftragsart (IV, Unfallversicherung,
              Haftpflicht/Gericht) wird aus dem Auftraggeber erkannt und ist in der Übersicht
              änderbar.</p>
            <label className="check-inline">
              <input type="checkbox" checked={withDraft}
                onChange={(e) => setWithDraft(e.target.checked)} />
              KI-Vorentwurf erstellen (markierte Vorschläge, vor der Freigabe zu prüfen)
            </label>
            <div className="row dialog-actions">
              <button onClick={() => setPending(null)}>Abbrechen</button>
              <button className="primary" onClick={startPending}>Auswertung starten</button>
            </div>
          </div>
        </div>
      )}
      {err && <p className="warn-note">Arbeitsliste konnte nicht geladen werden: {err}</p>}
      {opening && <p className="notice">{opening}</p>}

      {sys && !sys.extract_model && (
        <div className="setup-banner">
          <div>
            <strong>Sprachmodell fehlt.</strong> Texterkennung und Akte funktionieren bereits;
            für Register, Aktenauszug und Prüfung wird das lokale Sprachmodell benötigt.
          </div>
          <button className="primary" onClick={onSetup}>Einrichtung abschliessen</button>
        </div>
      )}

      {all.length > 0 && (
        <div className="kpis">
          <div className="kpi">
            <span className="kpi-value">{active.length}</span>
            <span className="kpi-label">Offene Fälle</span>
          </div>
          <div className={`kpi ${overdue ? "overdue" : due ? "soon" : ""}`}>
            <span className="kpi-value">{due}</span>
            <span className="kpi-label">
              Fristen ≤ 14 Tage{overdue ? ` · ${overdue} überfällig` : ""}
            </span>
          </div>
          <div className={`kpi ${review ? "soon" : ""}`}>
            <span className="kpi-value">{review}</span>
            <span className="kpi-label">Seiten zu prüfen</span>
          </div>
          <div className="kpi">
            <span className="kpi-value">{ready}</span>
            <span className="kpi-label">Bereit zur Auswertung</span>
          </div>
        </div>
      )}

      {showNew && (
        <NewCaseForm onCreated={onOpen} onCancel={() => setShowNew(false)} />
      )}

      {cases !== null && all.length === 0 && !showNew && (
        <EmptyState onNew={() => setShowNew(true)} />
      )}

      {all.length > 0 && (
        <>
          <div className="list-tools">
            <input
              className="search"
              placeholder="Suchen: Fall, Auftraggeber, Pseudonym"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <div className="segmented">
              {(["aktiv", "fertig", "alle"] as Filter[]).map((f) => (
                <button
                  key={f}
                  className={filter === f ? "on" : ""}
                  onClick={() => setFilter(f)}
                >
                  {f === "aktiv" ? "In Arbeit" : f === "fertig" ? "Fertig" : "Alle"}
                </button>
              ))}
            </div>
          </div>

          <table className="cases dash-table">
            <thead>
              <tr>
                <th>Fall</th>
                <th>Stand</th>
                <th>Nächste Frist / Termin</th>
                <th className="num">Akte</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c) => {
                const days = c.next_date ? daysUntil(c.next_date.date) : null;
                return (
                  <tr key={c.id} onClick={() => onOpen(c.id)}>
                    <td>
                      <div className="case-title">{c.title}</div>
                      <div className="muted small">
                        {[c.auftraggeber, JUR_LABEL[c.jurisdiction] ?? c.jurisdiction,
                          c.accident_date && `Unfall ${deDate(c.accident_date)}`]
                          .filter(Boolean).join(" · ")}
                      </div>
                    </td>
                    <td>
                      <StageBar stage={c.stage} />
                      {c.pipeline?.job_status === "running" && (
                        <div className="small run-state ok">● Auswertung läuft</div>
                      )}
                      {c.pipeline?.job_status === "queued" && (
                        <div className="small run-state">● wartet in der Warteschlange</div>
                      )}
                      {c.pipeline?.state === "interrupted" && (
                        <div className="small run-state warn">
                          unterbrochen —{" "}
                          <button className="link-btn" onClick={(e) => {
                            e.stopPropagation();
                            api.intake(c.id, !!c.pipeline?.vorentwurf)
                              .then(() => api.listCases().then(setCases));
                          }}>fortsetzen</button>
                        </div>
                      )}
                      {c.pipeline?.state === "error" && !c.pipeline.job_status && (
                        <div className="small run-state err">Auswertung mit Fehler beendet</div>
                      )}
                    </td>
                    <td>
                      {c.next_date && days !== null ? (
                        <div className={`deadline ${urgency(days)}`}>
                          <div>
                            {deDate(c.next_date.date)} ·{" "}
                            {KIND_LABEL[c.next_date.kind] ?? c.next_date.kind}
                          </div>
                          <div className="small">
                            {relative(days)}
                            {c.next_date.label ? ` · ${c.next_date.label}` : ""}
                          </div>
                        </div>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="num">
                      <div>{c.stats?.pages ?? 0} Bl.</div>
                      {(c.stats?.review ?? 0) > 0 && (
                        <div className="small review-count">{c.stats!.review} zu prüfen</div>
                      )}
                      {(c.stats?.pending ?? 0) > 0 && (
                        <div className="small muted">{c.stats!.pending} ohne OCR</div>
                      )}
                    </td>
                  </tr>
                );
              })}
              {shown.length === 0 && (
                <tr className="no-hover">
                  <td colSpan={4} className="muted">Keine Fälle für diese Auswahl.</td>
                </tr>
              )}
            </tbody>
          </table>
        </>
      )}

      <footer className="privacy">
        <span className="lock" aria-hidden>●</span>
        Alle Daten bleiben auf diesem Gerät – Texterkennung und Auswertung laufen lokal,
        ohne Internetverbindung. Jeder Fall wird laufend gespeichert und kann jederzeit
        wieder geöffnet werden; mehrere Akten werden nacheinander ausgewertet, eine
        unterbrochene Auswertung lässt sich fortsetzen.{" "}
        <strong>Forschungsprototyp, kein Medizinprodukt:</strong> alle Ergebnisse sind
        Entwürfe, die Sie an der Originalakte prüfen.
        {sys && (
          <span className="muted">
            {" "}Datenordner: <code>{sys.data_home}</code>
            {sys.extract_model ? ` · Modell: ${sys.extract_model}` : " · kein Sprachmodell installiert"}
            {` · Version ${sys.version}`}
          </span>
        )}
      </footer>
    </div>
  );
}
