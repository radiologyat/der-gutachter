// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { api, dur, friendlyCall, Job, progressText, STEP_LABEL } from "../api";

/** One quiet line while evaluations run in the background — for cases other than the
 *  one that is open (the open case shows its own flow). The program works on one case
 *  at a time; further cases wait in the queue. "Details" lists them in order. */
export default function ActivityBar({ currentCaseId, onOpenCase }: {
  currentCaseId: string | null;
  onOpenCase: (id: string) => void;
}) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const tick = () => api.activeJobs()
      .then((j) => alive && setJobs(j)).catch(() => alive && setJobs([]));
    tick();
    const t = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const others = jobs.filter((j) => j.case_id !== currentCaseId);
  if (!others.length) return null;
  const running = others.filter((j) => j.status === "running");
  const queued = others.filter((j) => j.status === "queued");
  const name = (j: Job) => j.case_title ?? (j.case_id === "_setup" ? "Einrichtung" : j.case_id);
  const step = (j: Job) => STEP_LABEL[j.step ?? ""] ?? j.step ?? "Vorbereitung";
  const stalled = (j: Job) => (j.idle_s ?? 0) > 300 && (!j.llm || j.llm.since_s > 600);

  return (
    <div className="activity">
      <div className="activity-row">
        <span className={`pulse ${running.length ? "" : "queued"}`} aria-hidden />
        <span>
          {running.length > 0 && (
            <>Im Hintergrund: <strong>{name(running[0])}</strong> – {step(running[0])}
              {running[0].total ? `, ${progressText(running[0].step, running[0].done,
                running[0].total)}` : ""}</>
          )}
          {running.length === 0 && "Auswertungen in der Warteschlange"}
          {queued.length > 0 && <span className="muted"> · {queued.length} weitere
            {queued.length === 1 ? " Akte wartet" : " Akten warten"}</span>}
          {running.some(stalled) && <span className="warn-note"> · keine Rückmeldung seit
            längerem, Protokoll prüfen</span>}
        </span>
        <span className="spacer" />
        <button className="link-btn" onClick={() => setOpen(!open)}>
          {open ? "ausblenden" : "Details"}
        </button>
      </div>
      {open && (
        <ol className="activity-list">
          {[...running, ...queued].map((j, i) => (
            <li key={j.id}>
              <button className="link-btn" onClick={() => j.case_id && onOpenCase(j.case_id)}>
                {name(j)}
              </button>{" "}
              {j.status === "queued" ? (
                <span className="muted">wartet (Platz {i})</span>
              ) : (
                <span className="muted">
                  {step(j)}{j.total ? `, ${progressText(j.step, j.done, j.total)}` : ""}
                  {j.llm ? ` · KI: ${friendlyCall(j.llm)}, seit ${dur(j.llm.since_s)}` : ""}
                  {` · läuft seit ${dur(j.elapsed_s)}`}
                  {j.eta_s != null ? ` · Rest ca. ${dur(j.eta_s)}` : ""}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
