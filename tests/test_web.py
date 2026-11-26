import html
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.web import views
from nparity import pipeline, store
from nparity.models import Run
from nparity.retry import RetryPolicy


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    d = tmp_path_factory.mktemp("runs")
    client = TestClient(app)
    run = pipeline.run(pipeline.RunConfig(old="http://testserver/v1", new="http://testserver/v2", workers=1,
                                          retry=RetryPolicy(base=0.0)), client)
    store.save(run, d)
    before, before_ledger = app.state.runs_dir, app.state.ledger_path
    app.state.runs_dir = d
    app.state.ledger_path = d / "accepted.yaml"          # never the repo's real ledger
    yield client, run
    app.state.runs_dir, app.state.ledger_path = before, before_ledger


def test_runs_page(setup):
    client, run = setup
    r = client.get("/")
    assert r.status_code == 200 and run.id in r.text


def test_run_page(setup):
    client, run = setup
    r = client.get(f"/runs/{run.id}")
    assert r.status_code == 200
    for s in ("Regressions", "10/10 correct", "$.total", "$.detail", "Noise removed", "hx-get"):
        assert s in r.text, s


def test_run_page_loads_htmx_locally(setup):
    client, run = setup
    r = client.get(f"/runs/{run.id}")
    assert r.status_code == 200
    assert "/static/htmx.min.js" in r.text
    assert "unpkg.com" not in r.text
    assert client.get("/static/htmx.min.js").status_code == 200


def test_finding_partial(setup):
    client, run = setup
    total = next(f for f in run.findings if f.path == "$.total")
    r = client.get(f"/runs/{run.id}/findings/{total.id}")
    assert r.status_code == 200
    assert "10.01" in r.text and "10.0" in r.text
    assert 'class="hl-old"' in r.text and 'class="hl-new"' in r.text
    rename = next(f for f in run.findings if f.kind == "renamed")
    r2 = client.get(f"/runs/{run.id}/findings/{rename.id}").text
    assert "fullName" in r2 and 'class="hl-new"' in r2       # highlights `name` on the new side


def test_mapping_page(setup):
    client, run = setup
    r = client.get(f"/runs/{run.id}/mapping")
    assert r.status_code == 200
    for s in ("GET /clients/{clientId}", "llm", "none (dropped)", "string, required → string | null, optional"):
        assert s in r.text, s


def test_verdict_with_regressions(setup):
    """PRD 0001 verdict: open items from review state (UX-2 placement kept)."""
    client, run = setup
    page = client.get(f"/runs/{run.id}").text
    verdict = "4 open items: 0 confirmed regressions, 4 need review"
    assert verdict in page
    assert page.index(verdict) < page.index('class="counts"')
    store.save(store.load("demo", Path(__file__).parent.parent / "runs"), app.state.runs_dir)
    demo = client.get("/runs/demo").text
    assert verdict in demo
    assert demo.index(verdict) < demo.index('class="counts"')


def test_verdict_clean_run(setup):
    client, _ = setup
    run = Run(id="clean", started_at=datetime.now(timezone.utc),
              config={"old": "http://a", "new": "http://b", "backend": "x", "requests": 0, "endpoints": 0})
    store.save(run, app.state.runs_dir)
    page = client.get("/runs/clean").text
    assert "Ready to cut over" in page
    assert "None." not in page
    assert page.count("Nothing to review") == 1


def test_reason_once_when_expanded(setup):
    client, run = setup
    f = next(f for f in run.findings if f.status == "shown" and f.reason)
    page = client.get(f"/runs/{run.id}").text
    expanded = page.split('<details class="f" open', 1)[1].split("</details>", 1)[0]
    assert expanded.count(html.escape(f.reason)) == 1
    assert html.escape(f.reason) not in client.get(f"/runs/{run.id}/findings/{f.id}").text


def test_no_dead_controls(setup):
    client, run = setup
    assert "ledger: stretch" not in client.get(f"/runs/{run.id}").text
    for f in run.findings:
        assert "disabled" not in client.get(f"/runs/{run.id}/findings/{f.id}").text


def test_static_and_404(setup):
    client, run = setup
    assert client.get("/static/nparity.css").status_code == 200
    assert client.get("/runs/nope").status_code == 404
    assert client.get(f"/runs/{run.id}/findings/f-999").status_code == 404
