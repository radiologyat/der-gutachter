// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { api, errorText, GuideQuestion, Interview } from "../api";
import type { OpenPage } from "../pages/CaseView";

const ORDER: GuideQuestion["origin"][] = ["finding", "beweisfrage", "llm", "standard"];
const ORIGIN_LABEL: Record<string, string> = {
  finding: "Klärung aus der Akte",
  beweisfrage: "Beweisfragen",
  llm: "Vorgeschlagene Klärungsfragen (Modell)",
  standard: "Standardthemen",
};

/** Interview guide built from the Akte; answers become section "Befragung". */
export default function InterviewPanel({ caseId, openPage }: {
  caseId: string; openPage: OpenPage;
}) {
  const [guide, setGuide] = useState<GuideQuestion[]>([]);
  const [iv, setIv] = useState<Interview>({});
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [proposal, setProposal] = useState<{ key: string; text: string; warning: string | null } | null>(null);

  useEffect(() => {
    api.interviewGuide(caseId).then(setGuide).catch((e) => setMsg(errorText(e)));
    api.getInterview(caseId).then(setIv);
  }, [caseId]);

  const answer = (id: string) => iv.answers?.[id] ?? "";
  const setAnswer = (id: string, text: string) =>
    setIv({ ...iv, answers: { ...(iv.answers ?? {}), [id]: text } });

  const save = async () => {
    const topics = Object.fromEntries(guide.map((g) => [g.id, g.topic]));
    try { await api.putInterview(caseId, { ...iv, topics }); setMsg("Gespeichert – wird beim nächsten Entwurf übernommen."); }
    catch (e) { setMsg(errorText(e)); }
  };
  const withModel = async () => {
    setBusy("Modell formuliert Klärungsfragen …");
    try { setGuide(await api.interviewGuide(caseId, true)); setMsg(""); }
    catch (e) { setMsg(errorText(e)); }
    setBusy("");
  };
  const indirect = async (key: string, text: string) => {
    setBusy("Formulierung …");
    try { const r = await api.toIndirect(caseId, text); setProposal({ key, text: r.text, warning: r.warning }); }
    catch (e) { setMsg(errorText(e)); }
    setBusy("");
  };
  const acceptProposal = () => {
    if (!proposal) return;
    if (proposal.key === "spontan") setIv({ ...iv, spontan: proposal.text });
    else setAnswer(proposal.key, proposal.text);
    setProposal(null);
  };

  const answered = Object.values(iv.answers ?? {}).filter((t) => t.trim()).length;
  const field = (key: string, value: string, onChange: (v: string) => void, rows = 2) => (
    <div className="answer-field">
      <textarea rows={rows} value={value} onChange={(e) => onChange(e.target.value)}
        placeholder="Angaben der versicherten Person" />
      {value.trim() && (
        <button className="link-btn" disabled={!!busy} onClick={() => indirect(key, value)}>
          in indirekte Rede
        </button>
      )}
      {proposal?.key === key && (
        <div className="proposal">
          <div>{proposal.text}</div>
          {proposal.warning && <div className="warn-note">{proposal.warning}</div>}
          <div className="row">
            <button onClick={acceptProposal}>Übernehmen</button>
            <button className="link" onClick={() => setProposal(null)}>Verwerfen</button>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="panel">
      <h3>Befragung {answered > 0 && <span className="muted small">· {answered} beantwortet</span>}</h3>
      <p className="muted small">Leitfaden aus der Akte: Unklarheiten, Widersprüche und Lücken
        werden zu Fragen, jeweils mit Grund und Fundstelle. Was Sie fragen, entscheiden Sie.
        Unbeantwortete Fragen erscheinen nicht im Gutachten.</p>
      <h4>Spontane Angaben</h4>
      {field("spontan", iv.spontan ?? "", (v) => setIv({ ...iv, spontan: v }), 3)}
      {ORDER.map((o) => {
        const qs = guide.filter((g) => g.origin === o);
        if (!qs.length) return null;
        return (
          <div key={o}>
            <h4>{ORIGIN_LABEL[o]}</h4>
            <ol className="guide">
              {qs.map((g) => (
                <li key={g.id}>
                  <div className="guide-q">{g.question}</div>
                  <div className="muted small">
                    {g.origin !== "standard" && <>Grund: {g.reason} </>}
                    {g.sources.map((s, i) => (
                      <button key={i} className="cite" onClick={() => openPage(s.global_seq, s.bbox)}>
                        Bl. {s.global_seq}
                      </button>
                    ))}
                  </div>
                  {field(g.id, answer(g.id), (v) => setAnswer(g.id, v))}
                </li>
              ))}
            </ol>
          </div>
        );
      })}
      <div className="row">
        <button className="primary" onClick={save}>Befragung speichern</button>
        <button disabled={!!busy} onClick={withModel}>Fragen vom Modell ergänzen</button>
        {busy && <span className="muted small">{busy}</span>}
        {msg && <span className="muted small">{msg}</span>}
      </div>
    </div>
  );
}
