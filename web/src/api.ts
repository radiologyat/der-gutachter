// SPDX-License-Identifier: AGPL-3.0-or-later
export interface CaseSummary {
  id: string;
  title: string;
  patient_ref: string;
  patient_dob: string | null;
  jurisdiction: string;
  case_type: string;
  accident_date: string | null;
  auftraggeber: string;
  notes: string | null;
  patient_name?: string | null;
  patient_address?: string | null;
  ahv_nr?: string | null;
  identity_check?: string | null;
  order_date?: string | null;
  received_date?: string | null;
  exam_date?: string | null;
  exam_start?: string | null;
  exam_end?: string | null;
  interpreter?: string | null;
  completed_date?: string | null;
  job_profile?: string | null;
  stage: string;
  next_date: { id: number; kind: string; date: string; label: string } | null;
  stats?: { pages: number; pending: number; review: number; documents: number };
  cover_pages_read?: [number, number] | null;
  pipeline?: {
    state?: "running" | "done" | "error" | "interrupted";
    vorentwurf?: boolean;
    full?: boolean;
    started?: string;
    finished?: string;
    error?: string | null;
    job_status?: "running" | "queued" | null;
  };
  updated_at?: string;
}

export interface PageRow {
  id: number;
  global_seq: number;
  page_no: number;
  status: "pending" | "ocr_done" | "review" | "manual";
  rotation: number;
  has_embedded_text: number;
  filename: string;
  snippet: string;
  text_md?: string;
  text_source?: string;
}

export interface OcrResult {
  total: number;
  ok: number;
  review: number;
  errors: number;
}

export interface Job<R = OcrResult> {
  id: string;
  kind: string;
  status: "running" | "queued" | "done" | "error" | "cancelled";
  case_id?: string;
  case_title?: string;
  elapsed_s?: number;
  idle_s?: number;
  eta_s?: number;
  llm?: { stage: string; ref: string; since_s: number };
  log?: { t: number; msg: string }[];
  total: number;
  done: number;
  current: number | null;
  step: string | null;
  error?: string;
  result?: R;
}

export interface AnalysisResult {
  cover?: { suggestions: number; verified: number };
  index?: { documents: number; pages: number; llm_failures: number };
  extract?: { facts: number; verified: number; unverified: number; llm_failures: number };
  timeline?: { entries: number; facts_used: number };
  checks?: { findings: number; by_type: Record<string, number>; kept_decisions: number };
  checks_ki?: { findings: number; dropped: number; error?: string };
  draft?: { generated: string[]; skipped: string[]; failed: string[] };
  vorentwurf?: { proposals: number };
}

export type BBox = [number, number, number, number];

export interface Citation {
  page_id: number;
  global_seq: number;
  block_ids: number[];
  bbox: BBox | null;
  quote: string;
  fact_id?: number;
  document_id?: number;
  doc_title?: string;
}

export interface Fact {
  id: number;
  document_id: number;
  doc_title: string | null;
  global_seq: number;
  fact_date: string | null;
  event_category: string | null;
  causality: string | null;
  laterality: string | null;
  title: string;
  summary: string | null;
  quote: string;
  bbox: BBox | null;
  verified: number;
  verify_note: string | null;
}

export interface Suggestion {
  id: number;
  auto?: number;
  kind: "case_field" | "date" | "question";
  payload: Record<string, string>;
  citation: Citation | null;
  verified: number;
  status: "open" | "accepted" | "rejected";
}

export interface Finding {
  id: number;
  type: string;
  severity: "low" | "medium" | "high";
  claim: string;
  explanation: string | null;
  source_a: Citation | null;
  source_b: Citation | null;
  status: "open" | "accepted" | "rejected";
  document_id: number | null;
  created_by?: string;
}

export interface ExpertProfile {
  name: string;
  title: string;
  address: string;
  sim_certificate: boolean;
  report_title?: string;
}

export interface GuideQuestion {
  id: string;
  topic: string;
  question: string;
  reason: string;
  origin: "standard" | "finding" | "beweisfrage" | "llm";
  sources: { global_seq: number; bbox: BBox | null }[];
}

export interface Interview {
  spontan?: string;
  answers?: Record<string, string>;
  topics?: Record<string, string>;
}

export interface Diagnosis {
  id: number;
  ord: number;
  text: string;
  icd10: string | null;
  laterality: string | null;
  since: string | null;
  af_relevant: number | null;
  source: string;
  fact_id: number | null;
}

export interface DiagnosisSuggestion {
  fact_id: number;
  title: string;
  icd10: string | null;
  laterality: string | null;
  fact_date: string | null;
  global_seq: number;
}

export interface SetupItem {
  id: string;
  label: string;
  description: string;
  size_gb: number;
  installed: boolean;
  available: boolean;
  reason: string | null;
  recommended: boolean;
}

export interface SetupStatus {
  system: {
    os: string;
    ram_gb: number | null;
    gpu: { name: string; vram_gb: number | null; cuda: string | null;
           cuda_ok: boolean | null; detected_by?: string; diag?: string } | null;
    apple_silicon: boolean;
    disk_free_gb: number;
    models_dir: string;
    llama_server: string | null;
  };
  items: SetupItem[];
  ready: boolean;
  job_id: string | null;
}

export interface LlmStatus {
  server_running: boolean;
  model_id: string | null;
  model_file: string | null;
  available: boolean;
}

export interface SystemInfo {
  disclaimer_version: string;
  disclaimer_acknowledged: boolean;
  app: string;
  version: string;
  data_home: string;
  models_dir: string;
  extract_model: string | null;
  tesseract: boolean;
  llama_server: boolean;
}

export interface CaseDate {
  id: number;
  kind: "begutachtung" | "frist" | "termin" | "sonstiges";
  date: string;
  label: string;
  done: number;
}

export interface IndexRow {
  id?: number;
  name?: string;
  title?: string;
  doc_type?: string;
  doc_date?: string | null;
  author?: string | null;
  institution?: string | null;
  boundary_reason?: string;
  verify_note?: string | null;
  start_seq: number;
  end_seq: number;
  pages?: number;
}

export interface TimelineRow {
  id: number;
  entry_date: string;
  date_end: string | null;
  category: string | null;
  causality: string | null;
  title: string;
  summary: string | null;
  laterality: string | null;
  citations: Citation[];
  created_by: string;
  edited: number;
  excluded: number;
  reviewed: number;
  original_json: string | null;
  updated_at: string | null;
}

export interface StepItem {
  key: string;
  label: string;
  tab: string;
  state: "offen" | "läuft" | "prüfen" | "ok" | "veraltet";
  detail: string;
  stale_because?: string[];
  recompute?: string[];
}

export interface ProtocolRow {
  ts: string;
  wer: string;
  aktion: string;
  detail: string;
}

export type TimelineEdit = Partial<{
  entry_date: string;
  date_end: string | null;
  category: string | null;
  causality: string | null;
  laterality: string | null;
  title: string;
  summary: string | null;
  seq: number | null;
  quote: string | null;
}>;

export interface DraftSection {
  id: number;
  ord: number;
  section_key: string;
  title: string;
  content_md: string;
  kind: "data" | "narrative" | "basis" | "questions" | "manual";
  status: "empty" | "draft" | "reviewed" | "approved";
  warnings: string[];
  problems: string[];
  style: { kind: string; text: string; hint: string }[];
  model_id: string | null;
  generated_at: string | null;
  approved_at: string | null;
}

export interface Question {
  id: number;
  ord: number;
  text: string;
  status: "open" | "answered" | "skipped";
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(`${status} ${typeof body === "string" ? body : JSON.stringify(body)}`);
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, init);
  if (!r.ok) {
    const text = await r.text();
    let body: unknown = text;
    try {
      body = JSON.parse(text);
    } catch {
      /* plain-text error */
    }
    throw new ApiError(r.status, body);
  }
  return r.json();
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  listCases: () => req<CaseSummary[]>("/cases"),
  getCase: (id: string) => req<CaseSummary>(`/cases/${id}`),
  createCase: (body: Record<string, unknown>) =>
    req<CaseSummary>("/cases", json("POST", body)),
  updateCase: (id: string, body: Record<string, unknown>) =>
    req<CaseSummary>(`/cases/${id}`, json("PATCH", body)),

  listDates: (id: string) => req<CaseDate[]>(`/cases/${id}/dates`),
  addDate: (id: string, kind: string, date: string, label: string) =>
    req<{ id: number }>(`/cases/${id}/dates`, json("POST", { kind, date, label })),
  setDateDone: (id: string, dateId: number, done: boolean) =>
    req(`/cases/${id}/dates/${dateId}`, json("PATCH", { done })),
  deleteDate: (id: string, dateId: number) =>
    req(`/cases/${id}/dates/${dateId}`, { method: "DELETE" }),

  listQuestions: (id: string) => req<Question[]>(`/cases/${id}/questions`),
  addQuestion: (id: string, ord: number, text: string) =>
    req(`/cases/${id}/questions`, json("POST", { ord, text })),

  getIndex: (id: string) => req<IndexRow[]>(`/cases/${id}/index`),
  getTimeline: (id: string) => req<TimelineRow[]>(`/cases/${id}/timeline`),
  addTimeline: (id: string, body: TimelineEdit) =>
    req<{ id: number }>(`/cases/${id}/timeline`, json("POST", body)),
  updateTimeline: (id: string, eid: number, body: TimelineEdit) =>
    req<TimelineRow>(`/cases/${id}/timeline/${eid}`, json("PATCH", body)),
  restoreTimeline: (id: string, eid: number) =>
    req<TimelineRow>(`/cases/${id}/timeline/${eid}/restore`, { method: "POST" }),
  flagTimeline: (id: string, eid: number, flag: "exclude" | "reviewed", value: boolean) =>
    req<TimelineRow>(`/cases/${id}/timeline/${eid}/${flag}`, json("POST", { value })),
  reviewAllTimeline: (id: string) =>
    req<{ reviewed: number }>(`/cases/${id}/timeline-review-all`, { method: "POST" }),
  deleteTimeline: (id: string, eid: number) =>
    req<{ ok: boolean }>(`/cases/${id}/timeline/${eid}`, { method: "DELETE" }),
  activeJobs: () => req<Job[]>(`/jobs-active`),
  readCoverPages: (id: string, start: number, end: number) =>
    req<{ job_id: string }>(`/cases/${id}/cover`, json("POST", { start, end })),
  refresh: (id: string) => req<{ job_id?: string; up_to_date?: boolean; steps: string[];
                                 ocr_pages?: number }>(`/cases/${id}/refresh`,
                                                       { method: "POST" }),
  diagnostics: (id: string) => req<Diagnostics>(`/cases/${id}/diagnostics`),
  gpuDiagnostics: () => req<Record<string, unknown>>(`/setup/gpu-diagnostics`),
  getSteps: (id: string) => req<{
    steps: StepItem[];
    progress?: { done: number; total: number; pct: number };
    todo?: { tab: string; text: string }[];
  }>(`/cases/${id}/steps`),
  getProtocol: (id: string) => req<ProtocolRow[]>(`/cases/${id}/protocol`),
  protocolCsv: (id: string) => `/api/cases/${id}/protocol.csv`,
  getDrafts: (id: string) => req<DraftSection[]>(`/cases/${id}/drafts`),
  updateSection: (id: string, key: string, body: { content_md?: string; status?: string }) =>
    req<{ status: string }>(`/cases/${id}/drafts/${key}`, json("PUT", body)),
  exportUrl: (id: string) => `/api/cases/${id}/export.docx`,

  upload: (id: string, files: FileList | File[]) => {
    const fd = new FormData();
    for (const f of Array.from(files)) fd.append("files", f);
    return req<{ results: { filename: string; status: string; pages_added: number }[] }>(
      `/cases/${id}/files`,
      { method: "POST", body: fd },
    );
  },
  runOcr: (id: string, engine = "tesseract") =>
    req<{ job_id: string }>(`/cases/${id}/ocr`, json("POST", { engine })),
  cancelJob: (jobId: string) => req(`/jobs/${jobId}/cancel`, { method: "POST" }),
  setupStatus: () => req<SetupStatus>("/setup/status"),
  setupInstall: (items: string[]) =>
    req<{ job_id: string }>("/setup/install", json("POST", { items })),
  setupImport: (folder: string) =>
    req<{ job_id: string }>("/setup/import", json("POST", { folder })),
  getJob: <R = OcrResult>(jobId: string) => req<Job<R>>(`/jobs/${jobId}`),

  analyze: (id: string, steps: string[]) =>
    req<{ job_id: string }>(`/cases/${id}/analyze`, json("POST", { steps })),
  llmStatus: () => req<LlmStatus>("/llm/status"),
  system: () => req<SystemInfo>("/system"),
  disclaimer: () => req<{ text: string }>("/disclaimer"),
  acknowledgeDisclaimer: () =>
    req<{ version: string; at: string }>("/disclaimer/acknowledge", { method: "POST" }),
  getFacts: (id: string, verified?: boolean) =>
    req<Fact[]>(`/cases/${id}/facts${verified === undefined ? "" : `?verified=${verified}`}`),
  getFindings: (id: string) => req<Finding[]>(`/cases/${id}/findings`),
  decideFinding: (id: string, fid: number, status: string) =>
    req(`/cases/${id}/findings/${fid}`, json("POST", { status })),
  excludeDocument: (id: string, docId: number, excluded: boolean) =>
    req(`/cases/${id}/documents/${docId}`, json("PATCH", { excluded })),
  getExpert: () => req<ExpertProfile>("/settings/expert"),
  putExpert: (p: ExpertProfile) => req<ExpertProfile>("/settings/expert", json("PUT", p)),
  getInterview: (id: string) => req<Interview>(`/cases/${id}/interview`),
  putInterview: (id: string, d: Interview) => req(`/cases/${id}/interview`, json("PUT", d)),
  interviewGuide: (id: string, model = false) =>
    req<GuideQuestion[]>(`/cases/${id}/interview/guide${model ? "?model=true" : ""}`),
  toIndirect: (id: string, text: string) =>
    req<{ text: string; changed_facts: boolean; warning: string | null }>(
      `/cases/${id}/interview/indirect`, json("POST", { text })),
  icd10Status: () => req<{ imported: boolean; version: string | null; codes: number }>(
    "/setup/icd10"),
  importIcd10: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<{ version: string; codes: number }>("/setup/icd10", { method: "POST", body: fd });
  },
  getExam: (id: string) => req<Record<string, unknown>>(`/cases/${id}/exam`),
  putExam: (id: string, d: Record<string, unknown>) => req(`/cases/${id}/exam`, json("PUT", d)),
  getAnswers: (id: string) => req<Record<string, unknown>>(`/cases/${id}/answers`),
  putAnswers: (id: string, d: Record<string, unknown>) =>
    req(`/cases/${id}/answers`, json("PUT", d)),
  getDiagnoses: (id: string) => req<Diagnosis[]>(`/cases/${id}/diagnoses`),
  diagnosisSuggestions: (id: string) =>
    req<DiagnosisSuggestion[]>(`/cases/${id}/diagnoses/suggestions`),
  addDiagnosis: (id: string, d: Partial<Diagnosis>) =>
    req<{ id: number }>(`/cases/${id}/diagnoses`, json("POST", d)),
  updateDiagnosis: (id: string, did: number, d: Partial<Diagnosis>) =>
    req(`/cases/${id}/diagnoses/${did}`, json("PUT", d)),
  deleteDiagnosis: (id: string, did: number) =>
    req(`/cases/${id}/diagnoses/${did}`, { method: "DELETE" }),
  icd10: (q: string) =>
    req<{ results: { code: string; text: string }[]; valid: boolean; normalized: string | null }>(
      `/icd10?q=${encodeURIComponent(q)}`),
  runningJob: (id: string) => req<{ job_id: string | null }>(`/cases/${id}/jobs/running`),
  intake: (id: string, vorentwurf = false) =>
    req<{ job_id: string }>(`/cases/${id}/intake${vorentwurf ? "?vorentwurf=true" : ""}`,
      { method: "POST" }),
  acceptProposals: (id: string, key: string) =>
    req<{ accepted: number }>(`/cases/${id}/drafts/${key}/accept-proposals`, { method: "POST" }),
  undoSuggestion: (id: string, sid: number) =>
    req(`/cases/${id}/suggestions/${sid}/undo`, { method: "POST" }),
  acceptVerified: (id: string) =>
    req<{ accepted: number }>(`/cases/${id}/suggestions/accept-verified`, { method: "POST" }),
  getSuggestions: (id: string) => req<Suggestion[]>(`/cases/${id}/suggestions`),
  decideSuggestion: (id: string, sid: number, accept: boolean) =>
    req<{ status: string }>(`/cases/${id}/suggestions/${sid}`, json("POST", { accept })),

  listPages: (id: string, status?: string) =>
    req<PageRow[]>(`/cases/${id}/pages${status ? `?status=${status}` : ""}`),
  getPage: (id: string, seq: number) => req<PageRow>(`/cases/${id}/pages/${seq}`),
  saveText: (id: string, seq: number, text: string) =>
    req<{ ok: boolean }>(`/cases/${id}/pages/${seq}/text`, json("PUT", { text })),
  pageImage: (id: string, seq: number) => `/api/cases/${id}/pages/${seq}/image`,
};

/** Start an analysis job and poll until it ends. Follows an already running job on 409. */
export async function runAnalysis(
  caseId: string,
  steps: string[],
  onProgress: (j: Job<AnalysisResult>) => void,
): Promise<Job<AnalysisResult>> {
  let jobId: string;
  try {
    ({ job_id: jobId } = await api.analyze(caseId, steps));
  } catch (e) {
    const running =
      e instanceof ApiError && e.status === 409
        ? (e.body as { detail?: { job_id?: string } })?.detail?.job_id
        : undefined;
    if (!running) throw e;
    jobId = running;
  }
  for (;;) {
    const j = await api.getJob<AnalysisResult>(jobId);
    onProgress(j);
    if (j.status !== "running") return j;
    await new Promise((r) => setTimeout(r, 700));
  }
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const b = e.body as { detail?: unknown } | string;
    if (typeof b === "object" && b && "detail" in b) {
      const d = b.detail as { detail?: string } | string;
      return typeof d === "string" ? d : (d?.detail ?? e.message);
    }
    return typeof b === "string" ? b : e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

export const STEP_LABEL: Record<string, string> = {
  Gutachtenauftrag: "Gutachtenauftrag",
  Deckblatt: "Gutachtenauftrag",
  "Texterkennung Auftrag": "Texterkennung Auftrag",
  Aktenauszug: "Aktenauszug",
  Prüfung: "Prüfung",
  "KI-Prüfung": "KI-Prüfung",
  Entwurf: "Entwurf",
  "KI-Vorentwurf": "KI-Vorentwurf",
  cover: "Gutachtenauftrag",
  index: "Registrierung",
  Registrierung: "Registrierung",
  extract: "Extraktion",
  Extraktion: "Extraktion",
  timeline: "Aktenauszug",
  checks: "Prüfung",
  checks_ki: "KI-Prüfung",
  draft: "Entwurf",
  vorentwurf: "KI-Vorentwurf",
};

export const DOC_TYPE_LABEL: Record<string, string> = {
  arztbrief: "Arztbrief",
  notfallbericht: "Notfallbericht",
  austrittsbericht: "Austrittsbericht",
  op_bericht: "OP-Bericht",
  radiologie: "Radiologie",
  labor: "Labor",
  rezept: "Verordnung",
  gutachten: "Gutachten",
  gericht: "Gericht",
  versicherung: "Versicherung",
  korrespondenz: "Korrespondenz",
  formular: "Formular",
  sonstiges: "Sonstiges",
};

export const CATEGORY_LABEL: Record<string, string> = {
  vorbefund: "Vorbefund",
  trauma: "Unfall",
  diagnostik: "Diagnostik",
  op: "Operation",
  konservativ: "Konservativ",
  reha: "Reha",
  arbeitsfaehigkeit: "Arbeitsfähigkeit",
  begutachtung: "Begutachtung",
  korrespondenz: "Korrespondenz",
};

export const CAUSALITY_LABEL: Record<string, string> = {
  vorschaden: "Vorschaden",
  unfallkausal: "unfallkausal",
  kombiniert: "kombiniert",
  unklar: "unklar",
  none: "—",
};

/** ISO date (YYYY-MM-DD, also partial) -> "14.03.2021" / "03.2021" / "2021". */
export function deDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return [d, m, y].filter(Boolean).join(".");
}

/** Whole days from today to an ISO date (negative = past). */
export function daysUntil(iso: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const t = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return Math.round((t.getTime() - today.getTime()) / 86_400_000);
}

export interface LlmBackend {
  build: string;
  device: string | null;
  gpu_layers: string | null;
  on_gpu: boolean;
}

export interface Diagnostics {
  ocr: { pages: number; pending: number; review: number; done: number; no_text: number;
         no_text_pages: number[]; duplicates: number; avg_chars: number;
         engines: Record<string, number>; errors: number };
  documents: { count: number; excluded: number; types: Record<string, number>;
               largest_pages: number };
  extraction: { statements: number; verified: number; rejected: number;
                reject_reasons: Record<string, number>; documents_without_statements: number };
  aktenauszug: number;
  findings: number;
  model_calls: Record<string, { ok: number; error: number; cache: number;
                                avg_s: number | null; max_s: number | null }>;
  model_errors: { stage: string; ref: string; error: string }[];
  llm_backend: LlmBackend | null;
  hints: string[];
}

/** "3 min 12 s" */
export function dur(s: number | undefined | null): string {
  if (s == null) return "—";
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${s % 60} s`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

type PyWebview = { api?: { save_download?: (path: string) => Promise<string | null> } };

/** Download a file of the local app. In the desktop window (which does not deliver
 *  browser downloads) a save dialog opens; in a normal browser the usual download.
 *  -> where it was saved (desktop) or null. */
export async function downloadFile(url: string): Promise<string | null> {
  const pv = (window as unknown as { pywebview?: PyWebview }).pywebview;
  if (pv?.api?.save_download) return pv.api.save_download(url);
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
  return null;
}

/** What a step counts, for "x von y" displays. */
export const STEP_UNIT: Record<string, string> = {
  "Texterkennung": "Seite", "Texterkennung Auftrag": "Seite", Registrierung: "Seite",
  index: "Seite", Extraktion: "Dokument", extract: "Dokument", Entwurf: "Abschnitt",
  draft: "Abschnitt", "KI-Vorentwurf": "Vorschlag", vorentwurf: "Vorschlag",
};

export function progressText(step: string | null | undefined, done: number,
                             total: number): string {
  if (!total) return "";
  const unit = STEP_UNIT[step ?? ""];
  return unit ? `${unit} ${done} von ${total}` : `${done} von ${total}`;
}

const CALL_STAGE: Record<string, string> = {
  page_analysis: "Register", fact_extract: "Extraktion", cover: "Gutachtenauftrag",
  checks_ki: "KI-Prüfung", draft_basis: "Entwurf", draft_narrative: "Entwurf",
  vorentwurf: "KI-Vorentwurf", vorentwurf_antwort: "KI-Vorentwurf",
  interview_guide: "Befragungsleitfaden",
};

/** The model call in plain words: "Extraktion, Dokument 5" instead of internal refs. */
export function friendlyCall(c: { stage: string; ref: string } | undefined | null): string {
  if (!c) return "";
  const stage = CALL_STAGE[c.stage] ?? c.stage;
  const doc = /^doc (\d+) chunk (\d+)/.exec(c.ref);
  if (doc) return `${stage}, Dokument ${doc[1]}${doc[2] !== "1" ? ` (Teil ${doc[2]})` : ""}`;
  const page = /^Bl\. ?(\d+)/.exec(c.ref);
  if (page) return `${stage}, Seite ${page[1]}`;
  return stage;  // drafting refs are internal (section/question keys)
}
