import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.main import app
from app.web.run_jobs import Job, RunJobs, stage_for

LEGACY_KEYS = {"state", "lines", "report_url", "error"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setitem(app.state._state, "runs_dir", tmp_path)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        yield client


def wait_for_job(client, job_url, predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(job_url)
        response.raise_for_status()
        job = response.json()
        if predicate(job):
            return job
        time.sleep(0.02)
    pytest.fail(f"Unexpected job state: {job}")


@pytest.mark.parametrize("line, stage", [
    ("Loading before source", "load"),
    ("Loading after source", "load"),
    ("Reading API endpoints", "read"),
    ("Mapping endpoints and fields (3 before, 4 after)", "map"),
    ("Replaying 12 requests", "replay"),
    ("Comparing responses and schemas", "compare"),
    ("Triaging 7 findings", "triage"),
    ("Saving report with 7 findings and 0 errors", "save"),
    ("Starting comparison", None),
    ("Baseline: 2026-01-01T000000-run", None),
    ("Saved configuration my-run", None),
    ("No requests generated. Add seeds for required parameters or request bodies.", None),
    ("Report saved", None),
    ("", None),
])
def test_stage_for_maps_progress_lines(line, stage):
    assert stage_for(line) == stage


def test_toy_run_reports_stage_per_progress_line(client):
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    with config.bind_socket() as listener:
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        try:
            response = client.post("/run-jobs", json={
                "before": {"kind": "api", "source": base + "/v1"},
                "after": {"kind": "spec", "source": base + "/v2/openapi.json"},
                "seeds": "fixtures/seeds.yaml", "intent": "fixtures/intent.md",
                "backend": "fake", "score": True,
            })
            assert response.status_code == 202
            job = wait_for_job(client, response.json()["job_url"],
                               lambda state: state["state"] in {"complete", "failed"})
        finally:
            server.should_exit = True
            thread.join(timeout=5)
    assert job["state"] == "complete", job
    assert LEGACY_KEYS <= job.keys()
    assert job["report_url"]
    assert job["stage"] == "save"


def test_unreachable_url_fails_in_load_stage(client):
    target = {"kind": "api", "source": "http://127.0.0.1:9"}
    response = client.post("/run-jobs", json={"before": target, "after": target})
    assert response.status_code == 202
    job = wait_for_job(client, response.json()["job_url"], lambda state: state["state"] == "failed")
    assert job["stage"] == "load"
    assert job["lines"][-1].startswith("Error: ")
    assert "reach the API document" in job["lines"][-1]


def test_stage_is_none_before_first_line():
    runs = RunJobs()
    runs.jobs["abc"] = Job()
    status = runs.status("abc")
    assert status["stage"] is None
    assert LEGACY_KEYS <= status.keys()
