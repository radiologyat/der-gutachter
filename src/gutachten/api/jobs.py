# SPDX-License-Identifier: AGPL-3.0-or-later
"""Simple in-process job manager for long-running stages (OCR, extraction)."""
from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable


class Job:
    def __init__(self, case_id: str, kind: str):
        self.id = uuid.uuid4().hex[:12]
        self.case_id = case_id
        self.kind = kind
        self.status = "running"  # running | done | error
        self.total = 0
        self.done = 0
        self.current = None
        self.step: str | None = None
        self.cancel = threading.Event()  # long jobs (downloads) check this
        self.result: dict | None = None
        self.error: str | None = None
        self.started_at = time.time()
        self.updated_at = self.started_at   # heartbeat: last progress of any kind
        self.step_started_at = self.started_at
        self.finished_at: float | None = None
        self.log: deque[tuple[float, str]] = deque(maxlen=60)  # what happened, in order

    def note(self, msg: str) -> None:
        self.updated_at = time.time()
        self.log.append((self.updated_at, msg))

    def set_progress(self, step: str | None, done: int, total: int) -> None:
        if step and step != self.step:
            self.step_started_at = time.time()
            self.note(f"Schritt: {step}")
        self.step, self.done, self.total = step or self.step, done, total
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        d = {k: v for k, v in vars(self).items() if k not in ("cancel", "log")}
        now = time.time()
        d["elapsed_s"] = int((self.finished_at or now) - self.started_at)
        d["idle_s"] = int(now - self.updated_at)
        d["log"] = [{"t": int(t - self.started_at), "msg": m} for t, m in self.log]
        # rough remaining time of the current step from its own rate
        if self.status == "running" and self.total and 0 < self.done < self.total:
            per = (now - self.step_started_at) / self.done
            d["eta_s"] = int(per * (self.total - self.done))
        from ..analysis.common import active_call

        if call := active_call(self.case_id):
            d["llm"] = {"stage": call["stage"], "ref": call["ref"],
                        "since_s": int(now - call["since"])}
        return d


class JobConflict(Exception):
    """A job of the same kind is already running for this case."""

    def __init__(self, job: Job):
        super().__init__(f"{job.kind} already running for {job.case_id}")
        self.job = job


# Analyses share one local language model: they run one after another. Further
# folders wait in the queue ("wartet") instead of slowing each other down.
QUEUED_KINDS = {"analysis"}
_model_slot = threading.Lock()


class JobManager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, case_id: str, kind: str, fn: Callable[[Job], dict]) -> Job:
        """Start a background job; raises JobConflict if one of the same kind
        is still running for the case (two OCR batches would double-process pages)."""
        with self._lock:
            for other in self.jobs.values():
                if (other.case_id == case_id and other.kind == kind
                        and other.status in ("running", "queued")):
                    raise JobConflict(other)
            job = Job(case_id, kind)
            self.jobs[job.id] = job

        def _run():
            from ..downloads import Cancelled

            held = False
            try:
                if kind in QUEUED_KINDS:
                    if not _model_slot.acquire(blocking=False):
                        job.status = "queued"
                        job.note("wartet, bis die laufende Auswertung fertig ist")
                        _model_slot.acquire()
                        job.status = "running"
                        job.started_at = job.step_started_at = time.time()
                    held = True
                job.note("gestartet")
                job.result = fn(job)
                job.status = "done"
                job.note("fertig")
            except Cancelled:
                job.status = "cancelled"
                job.error = "abgebrochen"
            except Exception as e:
                job.status = "error"
                job.error = str(e)
                job.note(f"Fehler: {e}")
            finally:
                if held:
                    _model_slot.release()
                job.finished_at = time.time()
                _record(job)

        threading.Thread(target=_run, daemon=True).start()
        return job

    def running(self, case_id: str, kind: str) -> Job | None:
        with self._lock:
            return next(
                (j for j in self.jobs.values()
                 if j.case_id == case_id and j.kind == kind
                 and j.status in ("running", "queued")),
                None,
            )

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def active(self) -> list[Job]:
        with self._lock:
            return [j for j in self.jobs.values() if j.status in ("running", "queued")]


def _record(job: Job) -> None:
    """Persist the finished job in the case's protocol (survives restarts)."""
    if job.case_id.startswith("_"):
        return
    try:
        from ..cases import connect_case
        from ..db import database

        conn = connect_case(job.case_id)
        try:
            summary = {"status": job.status, "dauer_s": int((job.finished_at or 0)
                                                           - job.started_at),
                       "fehler": job.error, "ergebnis": job.result}
            database.audit(conn, job.case_id, f"job_{job.kind}",
                           json.dumps(summary, ensure_ascii=False, default=str)[:4000])
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — the protocol must never break a job
        pass


jobs = JobManager()
