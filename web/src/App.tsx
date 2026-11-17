// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { api } from "./api";
import DisclaimerGate from "./components/DisclaimerGate";
import Setup from "./pages/Setup";
import Dashboard from "./pages/Dashboard";
import CaseView from "./pages/CaseView";
import ActivityBar from "./components/ActivityBar";

export default function App() {
  const [caseId, setCaseId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [ackNeeded, setAckNeeded] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);

  useEffect(() => {
    api
      .system()
      .then((s) => {
        setAckNeeded(!s.disclaimer_acknowledged);
        if (!s.extract_model) setSetupOpen(true); // first start: straight to setup
      })
      .catch(() => setAckNeeded(false));
  }, []);

  useEffect(() => {
    if (caseId) api.getCase(caseId).then((c) => setTitle(c.title));
    else setTitle("");
  }, [caseId]);

  return (
    <>
      <header>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setCaseId(null);
            setSetupOpen(false);
          }}
        >
          <span className="brand-mark" aria-hidden>G</span>
          <span className="app-name">Der Gutachter</span>
        </a>
        {caseId && (
          <>
            <span className="crumb">/ {title || caseId}</span>
            <span className="spacer" />
            <span className="offline-badge" title="Keine Daten verlassen dieses Gerät">
              lokal · offline
            </span>
            <a
              className="back"
              href="#"
              onClick={(e) => {
                e.preventDefault();
                setCaseId(null);
              }}
            >
              Arbeitsliste
            </a>
          </>
        )}
        {!caseId && (
          <>
            <span className="spacer" />
            <a
              className="back"
              href="#"
              onClick={(e) => {
                e.preventDefault();
                setSetupOpen(true);
              }}
            >
              Einrichtung
            </a>
            <span className="offline-badge" title="Keine Daten verlassen dieses Gerät">
              lokal · offline
            </span>
          </>
        )}
      </header>
      <ActivityBar
        currentCaseId={caseId}
        onOpenCase={(id) => {
          setSetupOpen(false);
          setCaseId(id);
        }}
      />
      {setupOpen ? (
        <Setup onDone={() => setSetupOpen(false)} />
      ) : caseId ? (
        <CaseView caseId={caseId} />
      ) : (
        <Dashboard onOpen={setCaseId} onSetup={() => setSetupOpen(true)} />
      )}
      {ackNeeded && <DisclaimerGate onAccepted={() => setAckNeeded(false)} />}
    </>
  );
}
