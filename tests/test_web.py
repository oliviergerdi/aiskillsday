import pytest
from fastapi.testclient import TestClient

from app.main import app
from nparity import pipeline, store
from nparity.retry import RetryPolicy


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    d = tmp_path_factory.mktemp("runs")
    client = TestClient(app)
    run = pipeline.run(pipeline.RunConfig(old="http://testserver/v1", new="http://testserver/v2", workers=1,
                                          retry=RetryPolicy(base=0.0)), client)
    store.save(run, d)
    before = app.state.runs_dir
    app.state.runs_dir = d
    yield client, run
    app.state.runs_dir = before


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


def test_static_and_404(setup):
    client, run = setup
    assert client.get("/static/nparity.css").status_code == 200
    assert client.get("/runs/nope").status_code == 404
    assert client.get(f"/runs/{run.id}/findings/f-999").status_code == 404
