# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from pydantic import BaseModel, Field


class CreateCaseRequest(BaseModel):
    title: str
    patient_ref: str = ""
    patient_dob: str | None = None
    jurisdiction: str = Field(default="CH", pattern="^(CH|AT|DE)$")
    case_type: str = "unfall"
    accident_date: str | None = None
    auftraggeber: str = ""


class UpdateCaseRequest(BaseModel):
    title: str | None = None
    patient_ref: str | None = None
    patient_dob: str | None = None
    jurisdiction: str | None = None
    case_type: str | None = None
    accident_date: str | None = None
    auftraggeber: str | None = None
    notes: str | None = None
    patient_name: str | None = None
    patient_address: str | None = None
    ahv_nr: str | None = Field(default=None, pattern=r"^(756\.?\d{4}\.?\d{4}\.?\d{2})?$")
    identity_check: str | None = None
    order_date: str | None = None
    received_date: str | None = None
    exam_date: str | None = None
    exam_start: str | None = Field(default=None, pattern=r"^(\d{2}:\d{2})?$")
    exam_end: str | None = Field(default=None, pattern=r"^(\d{2}:\d{2})?$")
    interpreter: str | None = None
    completed_date: str | None = None
    job_profile: str | None = None


class ExpertProfile(BaseModel):
    name: str = ""
    title: str = ""          # Facharzttitel
    address: str = ""
    sim_certificate: bool = False
    report_title: str = ""   # own title of the report; empty = default per assignment type


class DiagnosisRequest(BaseModel):
    text: str
    icd10: str | None = None
    laterality: str | None = None
    since: str | None = None
    af_relevant: int | None = None
    source: str = "eigen"
    fact_id: int | None = None
    ord: int | None = None


class AddDateRequest(BaseModel):
    kind: str = Field(default="termin", pattern="^(begutachtung|frist|termin|sonstiges)$")
    date: str
    label: str = ""


class UpdateDateRequest(BaseModel):
    done: bool


class UpdatePageTextRequest(BaseModel):
    text: str


class AddQuestionRequest(BaseModel):
    ord: int
    text: str


class RunOcrRequest(BaseModel):
    engine: str = "tesseract"  # 'tesseract' | 'vlm'
    vlm_model: str | None = None


class AnalyzeRequest(BaseModel):
    steps: list[str] = Field(
        default_factory=lambda: ["index", "extract", "timeline", "checks"]
    )


class SetupInstallRequest(BaseModel):
    items: list[str]


class SetupImportRequest(BaseModel):
    folder: str
    items: list[str] | None = None


class UpdateSectionRequest(BaseModel):
    content_md: str | None = None
    status: str | None = Field(default=None, pattern="^(draft|reviewed|approved)$")


class DecideFindingRequest(BaseModel):
    status: str = Field(pattern="^(open|accepted|rejected)$")


class UpdateDocumentRequest(BaseModel):
    excluded: bool


class DecideSuggestionRequest(BaseModel):
    accept: bool
