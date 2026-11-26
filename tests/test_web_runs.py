import asyncio
import json
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.main import app
from app.toys.v2 import app as new_toy
from nparity import store


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


@pytest.mark.parametrize("after_kind", ["spec_url", "spec_file", "manifest"])
def test_api_and_spec_run_streams_progress_and_saves_report(client, tmp_path, after_kind):
    release = threading.Event()

    async def serve_toys(scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/v1/openapi.json":
            assert await asyncio.to_thread(release.wait, 5)
        await app(scope, receive, send)

    config = uvicorn.Config(serve_toys, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    with config.bind_socket() as listener:
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        try:
            if after_kind == "spec_url":
                after = {"kind": "spec", "source": base + "/v2/openapi.json"}
            else:
                spec = tmp_path / "spec.json"
                spec.write_text(json.dumps(new_toy.openapi()), encoding="utf-8")
                after = {"kind": "spec", "source": str(spec), "base_url": base + "/v2"}
                if after_kind == "manifest":
                    manifest = tmp_path / "manifest.json"
                    manifest.write_text(json.dumps({"pairs": [{
                        "name": "toy", "new": {"url": base + "/v2/openapi.json", "file": spec.name},
                    }]}), encoding="utf-8")
                    after.update(kind="manifest", source=str(manifest) + "#toy")
            response = client.post("/run-jobs", json={
                "before": {"kind": "api", "source": base + "/v1"},
                "after": after,
                "seeds": "fixtures/seeds.yaml", "intent": "fixtures/intent.md",
                "backend": "fake", "score": True,
            })
            assert response.status_code == 202
            url = response.json()["job_url"]
            job = wait_for_job(client, url, lambda state: "Loading before source" in state["lines"])
            assert job["state"] == "running"
            release.set()
            job = wait_for_job(client, url, lambda state: state["state"] in {"complete", "failed"})
        finally:
            release.set()
            server.should_exit = True
            thread.join(timeout=5)
    assert job["state"] == "complete", job
    assert any("Replaying" in line for line in job["lines"])
    report = client.get(job["report_url"])
    assert report.status_code == 200
    assert "10/10 correct" in report.text


def test_capture_manifest_compares_saved_responses(client):
    source = "samples/api-versions/manifest.json#openfoodfacts_product"
    target = {"kind": "manifest", "source": source}
    response = client.post("/run-jobs", json={"before": target, "after": target})
    assert response.status_code == 202
    job = wait_for_job(client, response.json()["job_url"], lambda s: s["state"] in {"complete", "failed"})
    assert job["state"] == "complete", job
    report = store.load(job["report_url"].rsplit("/", 1)[1], app.state.runs_dir)
    assert report.config["requests"] == 1
    assert report.findings


def test_spec_path_requires_an_api_url_if_server_is_relative(client):
    target = {"kind": "spec", "source": "samples/api-versions/petstore_v3_spec.json"}
    response = client.post("/run-jobs", json={"before": target, "after": target})
    assert response.status_code == 202
    job = wait_for_job(client, response.json()["job_url"], lambda s: s["state"] == "failed")
    assert any("API base URL" in line for line in job["lines"])
    assert job["report_url"] is None


def test_run_rejects_cross_origin_submission(client):
    target = {"kind": "api", "source": "http://localhost/v1"}
    response = client.post("/run-jobs", json={"before": target, "after": target},
                           headers={"Origin": "https://example.com"})
    assert response.status_code == 403
