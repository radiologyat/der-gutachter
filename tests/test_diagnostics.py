# SPDX-License-Identifier: AGPL-3.0-or-later
"""Diagnosis, resumable runs, queue and activity — fictitious data only."""
import time

from gutachten.analysis import common
from gutachten.analysis.runner import run_analysis
from gutachten.api.jobs import JobManager
from gutachten.cases import connect_case

from .test_analysis import FakeLLM, akte  # noqa: F401
from .test_api import client


def test_diagnostics_counts_each_stage(akte):  # noqa: F811
    run_analysis(akte, ["index", "extract", "timeline", "checks"], llm_factory=FakeLLM)
    d = client.get(f"/api/cases/{akte}/diagnostics").json()
    assert d["ocr"]["pages"] > 0 and d["ocr"]["pending"] == 0
    assert d["documents"]["count"] > 0
    assert d["extraction"]["verified"] > 0 and d["extraction"]["rejected"] >= 1
    assert d["model_calls"]["fact_extract"]["ok"] > 0
    assert d["hints"]


def test_rerun_reuses_stored_model_answers(akte):  # noqa: F811
    """An interrupted or repeated run continues from stored answers."""
    calls = []

    class Counting(FakeLLM):
        def chat_json(self, messages, schema, schema_name="response", max_tokens=4096):
            calls.append(schema_name)
            return super().chat_json(messages, schema, schema_name, max_tokens)

    run_analysis(akte, ["index", "extract"], llm_factory=Counting)
    first = len(calls)
    run_analysis(akte, ["index", "extract"], llm_factory=Counting)
    assert first > 0 and len(calls) == first  # second run: no new model calls
    c = connect_case(akte)
    cached = c.execute("SELECT COUNT(*) FROM llm_calls WHERE status='cache'").fetchone()[0]
    c.close()
    assert cached == first


def test_analyses_queue_one_at_a_time():
    jm = JobManager()
    order = []

    def work(name):
        def fn(job):
            order.append(f"{name}-start")
            time.sleep(0.3)
            order.append(f"{name}-end")
            return {}
        return fn

    a = jm.start("caseA", "analysis", work("A"))
    time.sleep(0.05)
    b = jm.start("caseB", "analysis", work("B"))
    time.sleep(0.05)
    assert b.status == "queued" and b.to_dict()["log"][0]["msg"].startswith("wartet")
    for _ in range(40):
        if b.status == "done":
            break
        time.sleep(0.05)
    assert order == ["A-start", "A-end", "B-start", "B-end"] and a.status == "done"


def test_job_shows_current_model_call():
    jm = JobManager()
    seen = {}

    def fn(job):
        common._ACTIVE["caseX"] = {"stage": "fact_extract", "ref": "doc 3 chunk 1",
                                   "since": time.time() - 42}
        seen.update(job.to_dict())
        common._ACTIVE.pop("caseX", None)
        return {}

    jm.start("caseX", "ocr", fn)
    time.sleep(0.2)
    assert seen["llm"]["ref"] == "doc 3 chunk 1" and seen["llm"]["since_s"] >= 42
    assert "elapsed_s" in seen and "idle_s" in seen


def test_interrupted_run_is_reported(akte):  # noqa: F811
    from gutachten.cases import set_pipeline

    set_pipeline(akte, state="running", vorentwurf=True)
    c = client.get(f"/api/cases/{akte}").json()
    assert c["pipeline"]["state"] == "interrupted" and c["pipeline"]["vorentwurf"] is True
