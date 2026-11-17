// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { api, CaseSummary, errorText } from "../api";

type Field = { key: keyof CaseSummary; label: string; type?: string; span?: boolean;
  placeholder?: string; iv?: boolean };

const FIELDS: Field[] = [
  { key: "patient_name", label: "Name, Vorname (für das Gutachten)", span: true },
  { key: "patient_address", label: "Adresse", span: true },
  { key: "ahv_nr", label: "AHV-Nummer", placeholder: "756.1234.5678.97", iv: true },
  { key: "identity_check", label: "Identitätsprüfung", placeholder: "z. B. Identitätskarte" },
  { key: "order_date", label: "Auftragsdatum", type: "date" },
  { key: "received_date", label: "Eingangsdatum", type: "date" },
  { key: "exam_date", label: "Untersuchungsdatum", type: "date" },
  { key: "interpreter", label: "Dolmetscher (Sprache, leer = keiner)" },
  { key: "exam_start", label: "Untersuchung von", type: "time" },
  { key: "exam_end", label: "Untersuchung bis", type: "time" },
  { key: "completed_date", label: "Fertigstellung", type: "date" },
];

/** Formal details required in section 1.1 (KSVI Anhang IV; EKQMB C1: time from–to). */
export default function Formelles({ case_, onChanged }: {
  case_: CaseSummary;
  onChanged: () => void;
}) {
  const [form, setForm] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  useEffect(() => {
    const f: Record<string, string> = {};
    for (const x of FIELDS) f[x.key as string] = (case_[x.key] as string | null) ?? "";
    setForm(f);
  }, [case_]);

  const save = async () => {
    try {
      await api.updateCase(case_.id, form);
      setMsg("Gespeichert.");
      onChanged();
    } catch (e) {
      setMsg(errorText(e));
    }
  };

  const missing = FIELDS.filter((x) => (!x.iv || case_.case_type === "invaliditaet")
    && !["interpreter"].includes(x.key as string) && !form[x.key as string]).length;

  return (
    <div className="panel">
      <h3>Formelles für das Gutachten {missing > 0 && (
        <span className="warn-note"> · {missing} offen</span>)}</h3>
      <p className="muted small">
        Pflichtangaben unter „Ausgangslage und Formelles“, inkl. Untersuchungszeit von–bis.
        Ihre eigenen Angaben (Name, Facharzttitel) pflegen Sie einmalig unter „Einrichtung“.
      </p>
      <div className="form-grid">
        {FIELDS.filter((x) => !x.iv || case_.case_type === "invaliditaet").map((x) => (
          <label key={x.key as string} className={x.span ? "span2" : ""}>
            {x.label}
            <input
              type={x.type ?? "text"}
              placeholder={x.placeholder}
              value={form[x.key as string] ?? ""}
              onChange={(e) => setForm({ ...form, [x.key as string]: e.target.value })}
            />
          </label>
        ))}
      </div>
      <div className="row">
        <button className="primary" onClick={save}>Speichern</button>
        {msg && <span className="muted small">{msg}</span>}
      </div>
    </div>
  );
}
