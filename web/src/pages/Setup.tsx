// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import GpuCheck from "../components/GpuCheck";
import { api, errorText, ExpertProfile, Job, SetupStatus } from "../api";

function IcdPanel() {
  const [st, setSt] = useState<{ imported: boolean; version: string | null; codes: number } | null>(null);
  const [msg, setMsg] = useState("");
  const load = () => api.icd10Status().then(setSt).catch(() => setSt(null));
  useEffect(() => { load(); }, []);
  const upload = async (f: File) => {
    setMsg("Import läuft …");
    try { const r = await api.importIcd10(f); setMsg(`Importiert: ${r.codes} Codes (${r.version}).`); load(); }
    catch (e) { setMsg(errorText(e)); }
  };
  return (
    <div className="panel">
      <h3>ICD-10-GM-Katalog</h3>
      <p className="muted small">
        {st?.imported
          ? `Importiert: ${st.codes} Codes (${st.version}). Diagnosecodes werden auf Existenz geprüft.`
          : "Nicht importiert – Codes werden nur auf ihr Format geprüft, Vorschläge aus einer kurzen Liste."}
      </p>
      <p className="small">
        Den Katalog beziehen Sie einmalig selbst bei der offiziellen Stelle, im Format
        <strong> ClaML (XML)</strong>, und importieren ihn hier:
      </p>
      <ul className="small">
        <li>
          <strong>Deutsche Fassung</strong> (auch für die Schweiz):{" "}
          <a href="https://www.bfarm.de/DE/Kodiersysteme/Services/Downloads/_node.html"
            target="_blank" rel="noreferrer">BfArM – Downloads</a>, ICD-10-GM →
          Systematisches Verzeichnis → ClaML; kostenlos, mit Nutzungsvertrag beim Download.
        </li>
        <li>
          <strong>Welche Jahresversion in der Schweiz gilt</strong>, französische und
          italienische Fassung:{" "}
          <a href="https://www.bfs.admin.ch/bfs/de/home/statistiken/gesundheit/nomenklaturen/medkk/instrumente-medizinische-kodierung.html"
            target="_blank" rel="noreferrer">Bundesamt für Statistik – Instrumente der
            medizinischen Kodierung</a>.
        </li>
      </ul>
      <p className="muted small">
        Der Katalog wird aus Lizenzgründen nicht mit der Software verteilt: Die Rechte liegen
        bei BFS/BfArM bzw. der WHO; eine Weitergabe durch uns würde auch kommerzielle Nutzung
        Dritter ermöglichen, die eine Bewilligung braucht.
      </p>
      <label className="button-link">
        ClaML/XML-Datei importieren …
        <input type="file" accept=".xml" style={{ display: "none" }}
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      </label>
      {msg && <p className="notice">{msg}</p>}
    </div>
  );
}

function ExpertPanel() {
  const [p, setP] = useState<ExpertProfile>({ name: "", title: "", address: "",
    sim_certificate: false });
  const [msg, setMsg] = useState("");
  useEffect(() => { api.getExpert().then(setP).catch(() => undefined); }, []);
  const save = async () => {
    try { await api.putExpert(p); setMsg("Gespeichert."); } catch (e) { setMsg(errorText(e)); }
  };
  return (
    <div className="panel">
      <h3>Ihre Angaben als Sachverständige/r</h3>
      <p className="muted small">Erscheinen in jedem Gutachten unter „Formelles“ und bei der
        Unterschrift. Einmalig erfassen.</p>
      <div className="form-grid">
        <label>Name<input value={p.name} placeholder="Dr. med. …"
          onChange={(e) => setP({ ...p, name: e.target.value })} /></label>
        <label>Facharzttitel<input value={p.title}
          placeholder="FMH Orthopädische Chirurgie und Traumatologie des Bewegungsapparates"
          onChange={(e) => setP({ ...p, title: e.target.value })} /></label>
        <label className="span2">Praxisadresse<input value={p.address}
          onChange={(e) => setP({ ...p, address: e.target.value })} /></label>
        <label className="span2">Titel des Gutachtens (optional)<input
          value={p.report_title ?? ""}
          placeholder="leer = „Orthopädisch-traumatologisches Gutachten“ (CH)"
          onChange={(e) => setP({ ...p, report_title: e.target.value })} /></label>
        <label className="span2 check"><input type="checkbox" checked={p.sim_certificate}
          onChange={(e) => setP({ ...p, sim_certificate: e.target.checked })} />
          Zertifikat SIM (für Sozialversicherungsgutachten vorgeschrieben, Art. 7m ATSV)</label>
      </div>
      <div className="row"><button className="primary" onClick={save}>Speichern</button>
        {msg && <span className="muted small">{msg}</span>}</div>
    </div>
  );
}

type PyWebview = { api?: { pick_folder?: () => Promise<string | null> } };

export default function Setup({ onDone }: { onDone: () => void }) {
  const [st, setSt] = useState<SetupStatus | null>(null);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [job, setJob] = useState<Job<Record<string, unknown>> | null>(null);
  const [msg, setMsg] = useState("");
  const [folder, setFolder] = useState("");

  const load = async () => {
    const s = await api.setupStatus();
    setSt(s);
    setSel(new Set(s.items.filter((i) => i.recommended).map((i) => i.id)));
    if (s.job_id) follow(s.job_id);
  };
  useEffect(() => {
    load().catch((e) => setMsg(errorText(e)));
  }, []);

  const follow = async (jobId: string) => {
    for (;;) {
      const j = await api.getJob<Record<string, unknown>>(jobId);
      setJob(j);
      if (j.status !== "running") {
        setMsg(
          j.status === "done"
            ? "Fertig – Komponenten installiert und geprüft."
            : j.status === "cancelled"
              ? "Abgebrochen. Ein erneuter Start setzt den Download fort."
              : `Fehler: ${j.error}`,
        );
        setJob(null);
        load();
        return;
      }
      await new Promise((r) => setTimeout(r, 800));
    }
  };

  const start = async (fn: () => Promise<{ job_id: string }>) => {
    setMsg("");
    try {
      const { job_id } = await fn();
      follow(job_id);
    } catch (e) {
      setMsg(errorText(e));
    }
  };

  const pickFolder = async () => {
    const pw = (window as unknown as { pywebview?: PyWebview }).pywebview;
    const f = pw?.api?.pick_folder ? await pw.api.pick_folder() : null;
    if (f) setFolder(f);
  };

  if (!st) return <div className="dashboard"><p className="muted">{msg || "Lade …"}</p></div>;
  const s = st.system;
  const chosen = st.items.filter((i) => sel.has(i.id) && !i.installed);
  const gb = chosen.reduce((a, i) => a + i.size_gb, 0);
  const running = job?.status === "running";

  return (
    <div className="dashboard setup">
      <div className="dash-head">
        <div>
          <h1>Einrichtung</h1>
          <p className="muted">Sprachmodelle und GPU-Beschleunigung für die lokale Auswertung</p>
        </div>
        {st.ready && <button onClick={onDone}>Zur Arbeitsliste</button>}
      </div>

      <div className="kpis">
        <div className="kpi">
          <span className="kpi-value small-value">{s.ram_gb ?? "?"} GB</span>
          <span className="kpi-label">Arbeitsspeicher</span>
        </div>
        <div className="kpi">
          <span className="kpi-value small-value">
            {s.gpu ? (s.gpu.vram_gb != null ? `${s.gpu.vram_gb} GB` : "NVIDIA")
              : s.apple_silicon ? "Apple" : "—"}
          </span>
          <span className="kpi-label">
            {s.gpu
              ? `${s.gpu.name} · CUDA ${s.gpu.cuda ?? "unbekannt"}`
                + (s.gpu.detected_by === "Windows" ? " (über Windows erkannt)" : "")
              : s.apple_silicon ? "Apple Silicon (Metal)" : "keine NVIDIA-Grafikkarte erkannt"}
          </span>
        </div>
        <div className={`kpi ${s.disk_free_gb < 10 ? "soon" : ""}`}>
          <span className="kpi-value small-value">{s.disk_free_gb} GB</span>
          <span className="kpi-label">frei für Modelle</span>
        </div>
        <div className={`kpi ${st.ready ? "" : "soon"}`}>
          <span className="kpi-value small-value">{st.ready ? "bereit" : "fehlt"}</span>
          <span className="kpi-label">Sprachmodell</span>
        </div>
      </div>

      <GpuCheck />

      <div className="panel">
        <h3>Komponenten</h3>
        <ul className="setup-items">
          {st.items.map((i) => (
            <li key={i.id} className={i.available || i.installed ? "" : "na"}>
              <label>
                <input
                  type="checkbox"
                  disabled={i.installed || !i.available || running}
                  checked={i.installed || sel.has(i.id)}
                  onChange={(e) => {
                    const n = new Set(sel);
                    if (e.target.checked) n.add(i.id);
                    else n.delete(i.id);
                    setSel(n);
                  }}
                />
                <span className="grow">
                  <strong>{i.label}</strong> <span className="muted">· {i.size_gb.toFixed(1)} GB</span>
                  <div className="muted small">{i.description}</div>
                  {!i.installed && i.reason && <div className="warn-note">{i.reason}</div>}
                </span>
                <span className={`status ${i.installed ? "ocr_done" : "pending"}`}>
                  {i.installed ? "installiert" : i.available ? "nicht installiert" : "nicht verfügbar"}
                </span>
              </label>
            </li>
          ))}
        </ul>

        {running ? (
          <div className="setup-progress">
            <div className="muted small">{job?.step}</div>
            <div className="progress wide">
              <div style={{ width: `${(100 * (job?.done ?? 0)) / Math.max(job?.total ?? 1, 1)}%` }} />
            </div>
            <div className="row">
              <span className="muted small">
                {((job?.done ?? 0) / 1024).toFixed(2)} / {((job?.total ?? 0) / 1024).toFixed(2)} GB
              </span>
              <span className="grow" />
              <button onClick={() => job && api.cancelJob(job.id)}>Abbrechen</button>
            </div>
          </div>
        ) : (
          <>
            <div className="row" style={{ marginTop: 12 }}>
              <button
                className="primary"
                disabled={chosen.length === 0}
                onClick={() => start(() => api.setupInstall(chosen.map((i) => i.id)))}
              >
                {chosen.length ? `Herunterladen (${gb.toFixed(1)} GB)` : "Nichts ausgewählt"}
              </button>
            </div>
            <p className="muted small">
              Dies ist die einzige Internetverbindung der Anwendung: Es werden ausschliesslich
              Modelldateien von Hugging Face und GitHub geladen und per Prüfsumme (SHA-256)
              verifiziert. Es werden keine Falldaten übertragen. Ein abgebrochener Download wird
              beim nächsten Start fortgesetzt.
            </p>
          </>
        )}
        {msg && <p className="notice">{msg}</p>}
      </div>

      <ExpertPanel />
      <IcdPanel />

      <div className="panel">
        <h3>Ohne Internet: aus Ordner oder USB-Stick importieren</h3>
        <p className="muted small">
          Auf einem anderen Rechner geladene Modelldateien (gleiche Dateinamen) in einen Ordner
          kopieren, z. B. auf einen USB-Stick. Unterordner werden durchsucht; jede Datei wird vor
          der Übernahme geprüft.
        </p>
        <div className="row">
          <input
            style={{ flex: 1 }}
            placeholder="Ordner, z. B. E:\\Modellpaket"
            value={folder}
            onChange={(e) => setFolder(e.target.value)}
          />
          <button onClick={pickFolder} disabled={running}>Durchsuchen …</button>
          <button disabled={!folder || running} onClick={() => start(() => api.setupImport(folder))}>
            Importieren
          </button>
        </div>
        <details className="small">
          <summary className="muted">Welche Dateien gehören in den Ordner?</summary>
          <ul>
            <li><code>gemma-4-12b-it-qat-q4_0.gguf</code> – Sprachmodell</li>
            <li><code>llama-b12406-bin-win-cuda-13.5-x64.zip</code> und{" "}
              <code>cudart-llama-bin-win-cuda-13.5-x64.zip</code> – GPU-Beschleunigung</li>
          </ul>
        </details>
        <p className="muted small">Modellordner: <code>{s.models_dir}</code></p>
      </div>
    </div>
  );
}
