// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import {
  api, dur, friendlyCall, Job, progressText, StepItem, STEP_LABEL,
} from "../api";

export interface StepOverview {
  steps: StepItem[];
  progress?: { done: number; total: number; pct: number };
  todo?: { tab: string; text: string }[];
}

const ICON: Record<StepItem["state"], string> = {
  ok: "✓", prüfen: "!", offen: "○", läuft: "…", veraltet: "⟳",
};
const STATE_TEXT: Record<StepItem["state"], string> = {
  ok: "erledigt", prüfen: "zu prüfen", offen: "offen", läuft: "läuft", veraltet: "veraltet",
};
const INTERNAL: Record<string, string> = {
  ocr: "Texterkennung", cover: "Gutachtenauftrag", index: "Register", extract: "Angaben",
  timeline: "Aktenauszug", checks: "Prüfhinweise", checks_ki: "KI-Prüfung",
  exam: "Untersuchung/Fragen", draft: "Gutachten",
};
// the automatic part of the work, in the order it runs
const PIPELINE = ["Texterkennung Auftrag", "Gutachtenauftrag", "Texterkennung", "Registrierung",
  "Extraktion", "Aktenauszug", "Prüfung", "KI-Prüfung", "Entwurf", "KI-Vorentwurf"];

/** One navigation for the case: overview, the six work steps with their state, the
 *  protocol. Below: overall progress, what runs now and what comes next, and what is
 *  still missing – each item leads to the place where it is done. */
export default function CaseNav({
  caseId, data, active, onOpen, onRefresh, message,
}: {
  caseId: string;
  data: StepOverview | null;
  active: string;
  onOpen: (tab: string) => void;
  onRefresh: () => void;
  message: string;
}) {
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = () => api.activeJobs()
      .then((js) => alive && setJob(js.find((j) => j.case_id === caseId) ?? null))
      .catch(() => undefined);
    tick();
    const t = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(t); };
  }, [caseId]);

  const steps = data?.steps ?? [];
  const release = steps.find((s) => s.key === "freigabe");
  const work = steps.filter((s) => s.key !== "freigabe");
  const stale = steps.find((s) => s.state === "veraltet");

  const runningStep = job && job.status === "running"
    ? (STEP_LABEL[job.step ?? ""] ?? job.step ?? "") : "";
  const idx = PIPELINE.indexOf(runningStep);
  const next = idx >= 0 ? PIPELINE.slice(idx + 1) : [];

  const navItem = (key: string, label: string, extra?: StepItem, n?: number) => (
    <button key={key} className={`nav-item ${active === key ? "cur" : ""} ${extra
      ? `st-${extra.state}` : ""}`} onClick={() => onOpen(key)}
      title={extra ? `${STATE_TEXT[extra.state]} – ${extra.detail}` : undefined}>
      {extra && <span className="nav-ico">{ICON[extra.state]}</span>}
      <span className="nav-label">{n ? `${n}. ` : ""}{label}</span>
      {extra && <span className="nav-detail">{STATE_TEXT[extra.state]}</span>}
    </button>
  );

  return (
    <div className="casenav">
      <nav className="nav-row">
        {navItem("uebersicht", "Übersicht")}
        {work.map((s, i) => navItem(s.tab, s.label,
          s.key === "gutachten" && release && s.state === "ok"
            ? { ...s, state: release.state, detail: release.detail } : s, i + 1))}
        <span className="spacer" />
        {navItem("protokoll", "Protokoll")}
      </nav>

      {data?.progress && (
        <div className="flow">
          <div className="flow-progress">
            <span className="bar wide"><span style={{ width: `${data.progress.pct}%` }} /></span>
            <span className="small">
              Gesamtfortschritt {data.progress.pct} % · {data.progress.done} von{" "}
              {data.progress.total} Schritten erledigt
              {release ? ` · ${release.detail}` : ""}
            </span>
          </div>
          {job && (
            <div className="flow-now small">
              {job.status === "queued" ? (
                <span><strong>Wartet</strong> – eine andere Akte wird gerade ausgewertet.</span>
              ) : (
                <>
                  <span><strong>Jetzt:</strong> {runningStep || "Vorbereitung"}
                    {job.total ? ` – ${progressText(job.step, job.done, job.total)}` : ""}
                    {job.llm ? ` – KI: ${friendlyCall(job.llm)}, seit ${dur(job.llm.since_s)}`
                      : ""}
                    {job.eta_s != null ? ` – Rest dieses Schritts ca. ${dur(job.eta_s)}` : ""}
                  </span>
                  {next.length > 0 && (
                    <span className="muted"> · <strong>Danach:</strong> {next.join(" → ")}</span>
                  )}
                </>
              )}
            </div>
          )}
          {(data.todo?.length ?? 0) > 0 && (
            <div className="flow-todo small">
              <strong>Es fehlt noch:</strong>
              <ul>
                {data.todo!.map((t, i) => (
                  <li key={i}>
                    <button className="link-btn" onClick={() => onOpen(t.tab)}>{t.text}</button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.todo?.length === 0 && !job && (
            <div className="flow-todo small">Alle Schritte erledigt – das Gutachten kann
              exportiert werden.</div>
          )}
        </div>
      )}

      {stale && (
        <div className="stale-note">
          <span>
            <strong>{stale.label}</strong> ist veraltet – seit der letzten Berechnung geändert:{" "}
            {(stale.stale_because ?? []).map((x) => INTERNAL[x] ?? x).join(", ")}. Manuelle
            Korrekturen und bearbeitete Abschnitte bleiben beim Aktualisieren erhalten.
          </span>
          <button disabled={!!job} onClick={onRefresh}>Aktualisieren</button>
        </div>
      )}
      {message && <p className="notice small">{message}</p>}
    </div>
  );
}
