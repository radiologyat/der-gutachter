// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import { api, errorText } from "../api";

type Diag = {
  nvidia_smi?: string | null;
  nvidia_smi_result?: string;
  nvidia_smi_head?: string;
  adapters?: string[];
  gpu?: { name: string; cuda: string | null; cuda_ok: boolean | null;
          detected_by?: string } | null;
  llm_backend?: { build: string; device: string | null; gpu_layers: string | null;
                  on_gpu: boolean } | null;
};

/** Shows exactly what the graphics check saw – for "CUDA not detected" questions. */
export default function GpuCheck() {
  const [d, setD] = useState<Diag | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const run = async () => {
    setBusy(true);
    setErr("");
    try {
      setD((await api.gpuDiagnostics()) as Diag);
    } catch (e) {
      setErr(errorText(e));
    }
    setBusy(false);
  };
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Grafikkarte</h3>
        <button onClick={run} disabled={busy}>{busy ? "prüft …" : "Grafikkarte prüfen"}</button>
      </div>
      <p className="muted small">
        Ohne CUDA-Paket nutzt die App die mitgelieferte Vulkan-Version – auch damit rechnet
        eine NVIDIA-Karte. Nur wenn das Sprachmodell „nur Prozessor“ meldet, wird es langsam.
      </p>
      {err && <p className="warn-note">{err}</p>}
      {d && (
        <table className="cases small">
          <tbody>
            <tr><td>Erkannt</td><td>{d.gpu ? `${d.gpu.name} (über ${d.gpu.detected_by})`
              : "keine NVIDIA-Grafikkarte"}</td></tr>
            <tr><td>CUDA (Treiber)</td><td>{d.gpu?.cuda ?? "unbekannt"}
              {d.gpu?.cuda_ok === false && " – Treiber zu alt für das CUDA-Paket (13.5)"}</td></tr>
            <tr><td>nvidia-smi</td><td>{d.nvidia_smi ?? "nicht gefunden"} – {d.nvidia_smi_result}
            </td></tr>
            <tr><td>Grafikadapter (Windows)</td><td>{(d.adapters ?? []).join(", ") || "—"}</td></tr>
            <tr><td>Sprachmodell läuft auf</td><td>{d.llm_backend
              ? `${d.llm_backend.build}${d.llm_backend.device ? ` · ${d.llm_backend.device}` : ""}`
                + (d.llm_backend.gpu_layers ? ` · ${d.llm_backend.gpu_layers} Schichten auf GPU`
                  : "")
              : "noch nicht gestartet (startet bei der ersten Auswertung)"}</td></tr>
          </tbody>
        </table>
      )}
    </div>
  );
}
