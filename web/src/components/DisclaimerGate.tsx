// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { api } from "../api";

/** Blocks the app until the current disclaimer version is acknowledged. */
export default function DisclaimerGate({ onAccepted }: { onAccepted: () => void }) {
  const [text, setText] = useState("");
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.disclaimer().then((d) => setText(d.text)).catch(() => setText(""));
  }, []);

  const accept = async () => {
    setBusy(true);
    try {
      await api.acknowledgeDisclaimer();
      onAccepted();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="dg-title">
      <div className="modal">
        <h2 id="dg-title">Bevor Sie beginnen</h2>
        <p className="lead">
          <strong>Der Gutachter</strong> ist ein <strong>Forschungsprototyp</strong> und ein
          nicht-kommerzielles Open-Source-Projekt.
        </p>
        <ul className="key-points">
          <li><strong>Kein Medizinprodukt.</strong> Nicht für Diagnose oder Therapie bestimmt,
            nicht klinisch validiert.</li>
          <li><strong>Alles sind Entwürfe und Hinweise.</strong> Texterkennung und KI können
            Angaben erfinden, auslassen oder falsch zuordnen – prüfen Sie jede Angabe an der
            Originalakte.</li>
          <li><strong>Ihre Verantwortung.</strong> Die fachliche und rechtliche Verantwortung
            für ein Gutachten liegt allein bei der Person, die es unterzeichnet.</li>
          <li><strong>Keine Gewährleistung, keine Haftung</strong> der Urheber, soweit
            gesetzlich zulässig. Kein Support.</li>
          <li><strong>Datenschutz.</strong> Alle Daten bleiben auf diesem Gerät; für
            Verschlüsselung, Zugriffsschutz und Rechtsgrundlage sind Sie verantwortlich.</li>
        </ul>
        {text && (
          <details className="full-text">
            <summary>Vollständigen Haftungsausschluss lesen</summary>
            <pre>{text}</pre>
          </details>
        )}
        <label className="ack">
          <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
          Ich habe den Haftungsausschluss gelesen und verstanden. Ich verwende die Software
          auf eigene Verantwortung und prüfe alle Ergebnisse selbst.
        </label>
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 14 }}>
          <button className="primary" disabled={!checked || busy} onClick={accept}>
            Weiter
          </button>
        </div>
      </div>
    </div>
  );
}
