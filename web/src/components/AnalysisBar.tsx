// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { AnalysisResult, api, errorText, Job, LlmStatus, runAnalysis, STEP_LABEL } from "../api";

/** Run-button + progress + model status for analysis steps. */
export default function AnalysisBar({
  caseId,
  steps,
  label,
  onDone,
  describe,
}: {
  caseId: string;
  steps: string[];
  label: string;
  onDone: () => void;
  describe: (r: AnalysisResult) => string;
}) {
  const [job, setJob] = useState<Job<AnalysisResult> | null>(null);
  const [msg, setMsg] = useState("");
  const [llm, setLlm] = useState<LlmStatus | null>(null);

  useEffect(() => {
    api.llmStatus().then(setLlm).catch(() => setLlm(null));
  }, []);

  const run = async () => {
    setMsg("");
    try {
      const j = await runAnalysis(caseId, steps, setJob);
      setMsg(j.status === "done" && j.result ? describe(j.result) : `Fehler: ${j.error}`);
    } catch (e) {
      setMsg(errorText(e));
    }
    setJob(null);
    onDone();
  };

  const running = job?.status === "running";
  return (
    <div className="analysis-bar">
      <div className="toolbar" style={{ marginBottom: 6 }}>
        <button className="primary" onClick={run} disabled={running || llm?.available === false}>
          {label}
        </button>
        {running && (
          <>
            <span className="muted" style={{ fontSize: 12 }}>
              {STEP_LABEL[job.step ?? ""] ?? job.step ?? "…"}
              {job.total ? ` ${job.done}/${job.total}` : ""}
            </span>
            <div className="progress">
              <div style={{ width: `${(100 * job.done) / Math.max(job.total, 1)}%` }} />
            </div>
          </>
        )}
        <span className="grow" />
        {llm && (
          <span className="muted" style={{ fontSize: 12 }}>
            {llm.server_running
              ? `Modell: ${llm.model_id}`
              : llm.model_file
                ? `Modell: ${llm.model_file} (startet bei Bedarf)`
                : "Kein lokales Sprachmodell installiert"}
          </span>
        )}
      </div>
      {msg && <p className="notice">{msg}</p>}
    </div>
  );
}
