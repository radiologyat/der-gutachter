// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { api, BBox, CaseSummary, deDate, errorText } from "../api";
import UebersichtTab from "../components/UebersichtTab";
import AkteTab from "../components/AkteTab";
import RegisterTab from "../components/RegisterTab";
import AuszugTab from "../components/AuszugTab";
import GutachtenTab from "../components/GutachtenTab";
import HinweiseTab from "../components/HinweiseTab";
import UntersuchungTab from "../components/UntersuchungTab";
import CaseNav, { StepOverview } from "../components/CaseNav";
import ProtokollTab from "../components/ProtokollTab";

type TabKey = "uebersicht" | "akte" | "register" | "auszug" | "hinweise" | "untersuchung"
  | "gutachten" | "protokoll";

/** A citation target: page + optional region. `n` makes repeated clicks re-trigger. */
export interface PageFocus {
  seq: number;
  bbox: BBox | null;
  n: number;
}
export type OpenPage = (seq: number, bbox?: BBox | null) => void;

export default function CaseView({ caseId }: { caseId: string }) {
  const [case_, setCase] = useState<CaseSummary | null>(null);
  const [tab, setTab] = useState<TabKey>("uebersicht");
  const [focus, setFocus] = useState<PageFocus | null>(null);
  const openPage: OpenPage = (seq, bbox = null) => {
    setFocus((f) => ({ seq, bbox, n: (f?.n ?? 0) + 1 }));
    setTab("akte");
  };

  const [overview, setOverview] = useState<StepOverview | null>(null);
  const [rev, setRev] = useState(0); // remounts the open tab after a recompute
  const reload = () => {
    api.getCase(caseId).then(setCase);
    api.getSteps(caseId).then(setOverview).catch(() => undefined);
  };
  useEffect(() => {
    reload();
  }, [caseId, tab]);

  // the main action of a case: everything new or changed, as far as it goes
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const refresh = async () => {
    setBusy(true);
    setMsg("");
    try {
      const r = await api.refresh(caseId);
      if (r.up_to_date) {
        setMsg("Alles ist aktuell – es gibt nichts neu zu berechnen.");
      } else {
        for (;;) {
          await new Promise((res) => setTimeout(res, 1500));
          const j = await api.getJob(r.job_id!);
          if (j.status !== "running" && j.status !== "queued") {
            setMsg(j.status === "done" ? "Aktualisiert." : `Fehler: ${j.error ?? j.status}`);
            break;
          }
        }
      }
    } catch (e) {
      setMsg(`Fehler: ${errorText(e)}`);
    }
    setBusy(false);
    reload();
    setRev((x) => x + 1);
  };

  useEffect(() => {
    // the state of the steps changes while an evaluation runs in the background
    const t = setInterval(() => api.getSteps(caseId).then(setOverview)
      .catch(() => undefined), 5000);
    return () => clearInterval(t);
  }, [caseId]);

  return (
    <div className="case-shell">
      <div className="case-head">
        <div className="case-head-main">
          <strong>{case_?.title ?? caseId}</strong>
          {case_ && (
            <span className="muted">
              {case_.accident_date ? ` · Ereignis ${deDate(case_.accident_date)}` : ""}
              {case_.jurisdiction === "AT" ? " · Österreich" : ""}
            </span>
          )}
        </div>
        <div className="case-actions">
          <button className="primary big" onClick={refresh} disabled={busy}
            title="Erkennt neue Seiten und Änderungen, rechnet alles Betroffene neu und zeigt
              danach, was noch fehlt. Eigene Texte und Freigaben bleiben erhalten.">
            {busy ? "Wird aktualisiert …" : "Alles aktualisieren"}
          </button>
        </div>
      </div>
      {case_?.pipeline?.state === "interrupted" && (
        <div className="banner">
          <span>
            <strong>Auswertung unterbrochen</strong> (z. B. App geschlossen). Bereits Erledigtes
            ist gespeichert; beim Fortsetzen werden fertige Seiten und Modellantworten
            übernommen.
          </span>
          <button className="primary" onClick={() =>
            api.intake(caseId, !!case_.pipeline?.vorentwurf).then(reload)
              .catch((e) => alert(errorText(e)))}>Fortsetzen</button>
        </div>
      )}
      {case_?.pipeline?.state === "error" && !case_.pipeline.job_status && (
        <div className="banner err">
          <span>
            <strong>Auswertung mit Fehler beendet:</strong> {case_.pipeline.error}. Details
            unter „Protokoll“ (Diagnose).
          </span>
          <button onClick={() =>
            api.intake(caseId, !!case_.pipeline?.vorentwurf).then(reload)
              .catch((e) => alert(errorText(e)))}>Erneut versuchen</button>
        </div>
      )}
      <CaseNav caseId={caseId} data={overview} active={tab}
        onOpen={(t) => setTab(t as TabKey)} onRefresh={refresh} message={msg} />
      <div key={rev} className="tab-host">
      {tab === "uebersicht" && case_ && (
        <UebersichtTab case_={case_} onChanged={reload} openPage={openPage} />
      )}
      {tab === "akte" && (
        <AkteTab caseId={caseId} onChanged={reload} focus={focus} onAdded={refresh} />
      )}
      {tab === "register" && (
        <RegisterTab caseId={caseId} onChanged={reload} openPage={openPage} />
      )}
      {tab === "auszug" && (
        <AuszugTab caseId={caseId} openPage={openPage} onChanged={reload} />
      )}
      {tab === "hinweise" && (
        <HinweiseTab caseId={caseId} openPage={openPage} onChanged={reload} />
      )}
      {tab === "untersuchung" && case_ && (
        <UntersuchungTab case_={case_} openPage={openPage} />
      )}
      {tab === "gutachten" && <GutachtenTab caseId={caseId} />}
      {tab === "protokoll" && <ProtokollTab caseId={caseId} />}
      </div>
    </div>
  );
}
