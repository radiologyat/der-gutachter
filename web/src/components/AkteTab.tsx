// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, Job, PageRow } from "../api";
import type { PageFocus } from "../pages/CaseView";

const STATUS_LABEL: Record<string, string> = {
  pending: "offen",
  ocr_done: "OCR",
  review: "prüfen",
  manual: "manuell",
};

export default function AkteTab({
  caseId,
  onChanged,
  focus,
  onAdded,
}: {
  caseId: string;
  onChanged: () => void;
  onAdded?: () => void;
  focus?: PageFocus | null;
}) {
  const [pages, setPages] = useState<PageRow[]>([]);
  const [seq, setSeq] = useState<number | null>(focus?.seq ?? null);
  const [reviewOnly, setReviewOnly] = useState(false);
  const [highlight, setHighlight] = useState(focus?.bbox ?? null);
  const highlightRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!focus) return;
    setReviewOnly(false);
    setSeq(focus.seq);
    setHighlight(focus.bbox);
  }, [focus?.n]);

  useEffect(() => {
    highlightRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [highlight, seq]);
  const [page, setPage] = useState<PageRow | null>(null);
  const [text, setText] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [msg, setMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    const rows = await api.listPages(caseId, reviewOnly ? "review" : undefined);
    setPages(rows);
    if (rows.length && seq === null) setSeq(rows[0].global_seq);
  }, [caseId, reviewOnly, seq]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (seq === null) return;
    api.getPage(caseId, seq).then((p) => {
      setPage(p);
      setText(p.text_md ?? "");
    });
  }, [caseId, seq]);

  const upload = async (files: FileList) => {
    setMsg("Import läuft …");
    try {
      const r = await api.upload(caseId, files);
      const n = r.results.reduce((a, x) => a + x.pages_added, 0);
      const dups = r.results.filter((x) => x.status === "duplicate").length;
      const failed = r.results.filter((x) => x.status === "error");
      setMsg(
        `${r.results.length} Datei(en), ${n} Seiten importiert` +
          (dups ? `, ${dups} Duplikat(e) übersprungen` : "") +
          (failed.length
            ? `, ${failed.length} nicht lesbar: ${failed.map((x) => x.filename).join(", ")}`
            : "") +
          (n ? ". Die neuen Unterlagen werden jetzt ausgewertet." : "."),
      );
      if (n && onAdded) onAdded();  // recognise, register, extract, update the report
    } catch (e) {
      setMsg(`Import fehlgeschlagen: ${e instanceof Error ? e.message : e}`);
    }
    await refresh();
    onChanged();
  };

  const runOcr = async () => {
    let job_id: string;
    try {
      ({ job_id } = await api.runOcr(caseId));
    } catch (e) {
      // 409: an OCR batch is already running (e.g. started in another tab) – follow it.
      const running =
        e instanceof ApiError && e.status === 409
          ? (e.body as { detail?: { job_id?: string } })?.detail?.job_id
          : undefined;
      if (!running) {
        setMsg(`Texterkennung konnte nicht starten: ${e instanceof Error ? e.message : e}`);
        return;
      }
      job_id = running;
    }
    setMsg("Texterkennung läuft …");
    const poll = async () => {
      const j = await api.getJob(job_id);
      setJob(j);
      if (j.status === "running") {
        setTimeout(poll, 700);
      } else {
        setMsg(
          j.status === "done"
            ? `Texterkennung abgeschlossen: ${j.result?.ok} von ${j.result?.total} Seiten` +
                (j.result?.review ? `, ${j.result.review} zur Prüfung` : "") +
                (j.result?.errors ? `, ${j.result.errors} Fehler` : "") +
                "."
            : `Fehler: ${j.error}`,
        );
        refresh();
        onChanged();
      }
    };
    poll();
  };

  const save = async () => {
    if (seq === null) return;
    await api.saveText(caseId, seq, text);
    setMsg(`Bl. ${seq} d. A. gespeichert.`);
    refresh();
  };

  const sourceLabel =
    page?.text_source === "manual"
      ? "manuell erfasst"
      : page?.text_source === "embedded"
        ? "aus Textebene"
        : page?.text_source === "ocr"
          ? "Texterkennung"
          : "noch kein Text";

  return (
    <div className="case-view">
      <div className="col">
        <div className="toolbar">
          <button className="primary" onClick={() => fileRef.current?.click()}>
            Unterlagen hinzufügen …
          </button>
          <button onClick={() => folderRef.current?.click()}>Ordner hinzufügen …</button>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.docx,.rtf,.txt,.md,.html,.htm,.eml,.mp3,.m4a,.wav"
            style={{ display: "none" }}
            onChange={(e) => e.target.files && upload(e.target.files)}
          />
          <input
            ref={folderRef}
            type="file"
            multiple
            style={{ display: "none" }}
            // @ts-expect-error non-standard attribute for folder upload
            webkitdirectory=""
            onChange={(e) => e.target.files && upload(e.target.files)}
          />
          <button onClick={runOcr} disabled={job?.status === "running"}>
            OCR
          </button>
        </div>
        <div className="toolbar">
          <label className="muted" style={{ fontSize: 12 }}>
            <input
              type="checkbox"
              checked={reviewOnly}
              onChange={(e) => {
                setReviewOnly(e.target.checked);
                setSeq(null);
              }}
            />{" "}
            nur zu prüfende Seiten
          </label>
          {job?.status === "running" && (
            <div className="progress">
              <div style={{ width: `${(100 * job.done) / Math.max(job.total, 1)}%` }} />
            </div>
          )}
        </div>
        <p className="notice">{msg}</p>
        {pages.map((p) => (
          <div
            key={p.global_seq}
            className={`thumb ${p.global_seq === seq ? "active" : ""}`}
            onClick={() => {
              setSeq(p.global_seq);
              setHighlight(null);
            }}
          >
            <img src={api.pageImage(caseId, p.global_seq)} loading="lazy" />
            <div className="tlabel">
              <span>Bl. {p.global_seq} d. A.</span>
              <span className={`status ${p.status}`}>{STATUS_LABEL[p.status]}</span>
            </div>
          </div>
        ))}
        {pages.length === 0 && (
          <p className="empty">
            Aktenmappe laden („Ordner laden“) – die Seiten erhalten automatisch eine
            Blattzahlung („Bl. N d. A.“).
          </p>
        )}
      </div>

      <div className="col center">
        <p className="col-title">
          Scan · Bl. {seq ?? "–"} d. A.{page?.filename ? ` · ${page.filename}` : ""}
        </p>
        {seq ? (
          <div className="page-wrap">
            <img className="page-img" src={api.pageImage(caseId, seq)} />
            {highlight && (
              <div
                ref={highlightRef}
                className="cite-box"
                style={{
                  left: `${highlight[0] * 100}%`,
                  top: `${highlight[1] * 100}%`,
                  width: `${(highlight[2] - highlight[0]) * 100}%`,
                  height: `${(highlight[3] - highlight[1]) * 100}%`,
                }}
              />
            )}
          </div>
        ) : (
          <p className="empty">Seite wählen</p>
        )}
      </div>

      <div className="col right">
        <div className="toolbar">
          <p className="col-title" style={{ margin: 0 }}>
            Text <span className="muted">({sourceLabel})</span>
          </p>
          <span className="grow" />
          <button onClick={save} disabled={seq === null}>Speichern</button>
        </div>
        <textarea
          className="text-md"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Erkannter Text erscheint hier. Handschriftliche Stellen können hier manuell übertragen werden."
        />
      </div>
    </div>
  );
}
