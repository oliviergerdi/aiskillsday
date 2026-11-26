"""PRD 0001 web: configurations, rerun with baseline, decisions, sign-off."""

import shutil
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.main import app
from nparity import store


@pytest.fixture(scope="module")
def toys():
    """The toy services on a real port, so web-started runs can replay them."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    with config.bind_socket() as sock:
        t = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        t.start()
        while not server.started:
            time.sleep(0.01)
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        server.should_exit = True
        t.join(5)


@pytest.fixture
def client(tmp_path, monkeypatch):
    comps = tmp_path / "comparisons"
    shutil.copytree("comparisons", comps)
    monkeypatch.setitem(app.state._state, "runs_dir", tmp_path / "runs")
    monkeypatch.setitem(app.state._state, "comparisons_dir", comps)
    monkeypatch.setitem(app.state._state, "ledger_path", tmp_path / "accepted.yaml")
    (tmp_path / "runs").mkdir()
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        c.tmp = tmp_path
        yield c


def wait(client, job_url):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = client.get(job_url).json()
        if job["state"] != "running":
            assert job["state"] == "complete", job["lines"]
            return job
        time.sleep(0.05)
    pytest.fail("job did not finish")


def start(client, toys, **kw):
    body = {"before": {"kind": "api", "source": toys + "/v1"}, "after": {"kind": "api", "source": toys + "/v2"},
            "seeds": "fixtures/seeds.yaml", "intent": "fixtures/intent.md", "backend": "fake", "score": True,
            "name": "toy", **kw}
    r = client.post("/run-jobs", json=body)
    assert r.status_code == 202, r.text
    job = wait(client, r.json()["job_url"])
    return store.load(job["report_url"].removeprefix("/runs/"), client.tmp / "runs")


def test_comparisons_json(client):
    names = {c["name"] for c in client.get("/comparisons").json()}
    assert {"toy", "petstore"} <= names
    assert client.get("/comparisons/toy").json()["config"]["backend"] == "fake"
    assert client.get("/comparisons/nope").status_code == 404


def test_rerun_records_config_and_auto_baseline(client, toys):
    first = start(client, toys, baseline="")
    assert first.config["config"] == "toy" and first.config["baseline"] is None
    second = start(client, toys)                                   # baseline defaults to auto
    assert second.config["baseline"] == first.id
    third = start(client, toys, baseline=first.id)
    assert third.config["baseline"] == first.id
    runs = client.get("/comparisons/toy").json()["runs"]
    assert [r["id"] for r in runs][:3] == [third.id, second.id, first.id]
    assert runs[0]["open"] == 4


def test_save_config(client, toys):
    run = start(client, toys, name="mytoy", save_config=True, baseline="")
    assert (client.tmp / "comparisons" / "mytoy.yaml").is_file()
    assert run.config["config"] == "mytoy"


def test_non_local_refused():
    with TestClient(app, base_url="http://localhost", client=("10.0.0.5", 50000)) as c:
        assert c.get("/comparisons").status_code == 403



# ---- decisions, run page, sign-off (Tasks 6-8) ----

from nparity import pipeline  # noqa: E402
from nparity.retry import RetryPolicy  # noqa: E402
from nparity.review import Ledger  # noqa: E402


@pytest.fixture
def saved(client):
    run = pipeline.run(pipeline.RunConfig(old="http://testserver/v1", new="http://testserver/v2", workers=1,
                                          retry=RetryPolicy(base=0.0)), TestClient(app))
    run.config["config"] = "toy"
    store.save(run, client.tmp / "runs")
    return run


def fid(run, path):
    return next(f.id for f in run.findings if f.path == path)


def decide(client, run, path, decision, by="Temba", note=""):
    return client.post(f"/runs/{run.id}/findings/{fid(run, path)}/decision",
                       json={"decision": decision, "by": by, "note": note})


def test_accept_records_and_moves_section(client, saved):
    r = decide(client, saved, "$.detail", "accept", note="wording agreed")
    assert r.status_code == 200, r.text
    (e,) = Ledger.load(client.tmp / "accepted.yaml").entries
    assert (e.scope, e.decision, e.by, e.model_label) == ("toy", "accept", "Temba", "unsure")
    page = client.get(f"/runs/{saved.id}").text
    assert "Accepted by reviewer" in page
    assert "3 open items: 0 confirmed regressions, 3 need review" in page
    body = client.get(f"/runs/{saved.id}/findings/{fid(saved, '$.detail')}").text
    assert "Accepted</b> by Temba" in body and "wording agreed" in body and "data-undo" in body


def test_reject_intended_blocks(client, saved):
    assert decide(client, saved, "status", "reject").status_code == 200
    page = client.get(f"/runs/{saved.id}").text
    assert "Confirmed regressions</span> rejected by a reviewer" in page
    assert "5 open items: 1 confirmed regression, 4 need review" in page


def test_undo(client, saved):
    decide(client, saved, "$.detail", "accept")
    r = client.delete(f"/runs/{saved.id}/findings/{fid(saved, '$.detail')}/decision")
    assert r.json() == {"removed": True}
    assert Ledger.load(client.tmp / "accepted.yaml").entries == []


def test_bad_decisions(client, saved):
    assert decide(client, saved, "$.detail", "accept", by="  ").status_code == 422
    assert decide(client, saved, "$.detail", "maybe").status_code == 422
    assert client.post(f"/runs/{saved.id}/findings/f-999/decision",
                       json={"decision": "accept", "by": "T"}).status_code == 404


def test_decision_refused_from_non_local(saved, client):
    """Review focus 5."""
    with TestClient(app, base_url="http://localhost", client=("10.0.0.5", 50000)) as other:
        r = other.post(f"/runs/{saved.id}/findings/{fid(saved, '$.detail')}/decision",
                       json={"decision": "accept", "by": "T"})
    assert r.status_code == 403


def test_baseline_header_and_override(client, saved):
    from datetime import timedelta
    second = saved.model_copy(update={"id": saved.id + "-2", "started_at": saved.started_at + timedelta(minutes=1),
                                      "config": {**saved.config, "baseline": saved.id}})
    store.save(second, client.tmp / "runs")
    page = client.get(f"/runs/{second.id}").text
    assert "<b>0</b> new · <b>8</b> unchanged · <b>0</b> resolved" in page
    none = client.get(f"/runs/{second.id}?baseline=").text
    assert "No baseline" in none


def test_signoff_page(client, saved):
    decide(client, saved, "$.detail", "accept", note="ok")
    decide(client, saved, "$.total", "reject", note="rounding bug")
    page = client.get(f"/runs/{saved.id}/signoff").text
    assert "Cutover sign-off" in page
    assert "3 open items: 1 confirmed regression, 2 need review" in page
    assert page.index("confirmed regression</span>") < page.index("needs review</span>")
    assert "Rejected by Temba" in page and "rounding bug" in page
    assert "Accepted by reviewer" in page and "unsure p=" in page
    assert "p ≥ 0.98" in page and "p ≥ 0.999" in page
    assert "Names are typed, not authenticated" in page


def test_signoff_lists_stale_entries(client, saved):
    decide(client, saved, "$.total", "accept")
    gone = saved.model_copy(update={"id": saved.id + "-fixed",
                                    "findings": [f for f in saved.findings if f.path != "$.total"]})
    store.save(gone, client.tmp / "runs")
    assert "No longer seen" in client.get(f"/runs/{gone.id}/signoff").text


def test_print_css_hides_controls():
    css = open("app/web/static/nparity.css").read()
    assert "@media print" in css and ".decision" in css.split("@media print", 1)[1]
