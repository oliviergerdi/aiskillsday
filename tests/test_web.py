import html
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.web import views
from nparity import pipeline, store
from nparity.models import Finding, Run
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


def test_verdict_with_regressions(setup):
    client, run = setup
    c = views.counts(run)
    page = client.get(f"/runs/{run.id}").text
    verdict = f"{c['regression']} regressions and {c['unsure']} unsure need review"
    assert verdict in page
    assert page.index(verdict) < page.index('class="counts"')
    store.save(store.load("demo", Path(__file__).parent.parent / "runs"), app.state.runs_dir)
    demo = client.get("/runs/demo").text
    assert "3 regressions and 1 unsure need review" in demo
    assert demo.index("3 regressions and 1 unsure need review") < demo.index('class="counts"')


def test_verdict_clean_run(setup):
    client, _ = setup
    run = Run(id="clean", started_at=datetime.now(timezone.utc),
              config={"old": "http://a", "new": "http://b", "backend": "x", "requests": 0, "endpoints": 0})
    store.save(run, app.state.runs_dir)
    page = client.get("/runs/clean").text
    assert "No regressions found" in page
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


def _finding(i, status):
    return Finding(id=f"f-{i}", endpoint="GET /x", path=f"$.f{i}", kind="changed", source="diff", status=status)


def _table(page):
    """Return (headers, rows) of the runs table; each row is a list of raw <td> html."""
    tags = lambda s: re.sub(r"<[^>]+>", "", s).strip()
    heads = [tags(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", page, re.S)]
    body = page.split("<tbody>", 1)[1]
    rows = [re.findall(r"<td[^>]*>.*?</td>", r, re.S) for r in body.split("<tr")[1:]]
    return heads, rows


@pytest.fixture
def one_run(tmp_path):
    before = app.state.runs_dir
    app.state.runs_dir = tmp_path
    findings = [_finding(i, "shown") for i in range(40)] + [_finding(40 + i, "unsure") for i in range(11)]
    run = Run(id="run-abc123xyz", started_at=datetime(2026, 3, 14, 9, 30, tzinfo=timezone.utc), findings=findings,
              config={"old": "http://a", "new": "http://b", "backend": "fake", "requests": 0, "endpoints": 0})
    store.save(run, tmp_path)
    yield TestClient(app), run
    app.state.runs_dir = before


def test_runs_page_needs_review(one_run):
    client, _ = one_run
    heads, rows = _table(client.get("/").text)
    assert "Needs review" in heads
    cell = rows[0][heads.index("Needs review")]
    assert ">51<" in re.sub(r"\s+", "", cell)


def test_runs_page_zero_counts_muted(one_run):
    client, run = one_run
    run.findings += [_finding(100, "accepted"), _finding(101, "accepted")]
    store.save(run, app.state.runs_dir)
    heads, rows = _table(client.get("/").text)
    cells = dict(zip(heads, rows[0]))
    has_zero = lambda c: re.search(r'class="[^"]*\bzero\b', c) is not None
    assert has_zero(cells["Noise"]) and has_zero(cells["Errors"])
    assert not has_zero(cells["Intended"])            # 2 intended
    assert not has_zero(cells["Needs review"])        # 51


def test_runs_page_run_column(one_run):
    client, run = one_run
    page = client.get("/").text
    heads, rows = _table(page)
    link = re.search(rf'<a[^>]*href="/runs/{run.id}"[^>]*>(.*?)</a>', rows[0][0], re.S)
    assert link and link.group(1).strip() != run.id and link.group(1).strip()
    assert f'title="{run.id}"' in rows[0][0]
    backend = rows[0][heads.index("Backend")]
    assert "Fake" in backend and 'title="fake"' in backend
    assert "Time" not in heads and "Cost" not in heads


def test_nav_labels_and_brand_link(setup):
    client, run = setup
    nav = lambda p: re.findall(r"<a[^>]*>(.*?)</a>", re.search(r"<nav.*?</nav>", p, re.S).group(0), re.S)
    home = client.get("/").text
    assert re.search(r'<a[^>]*href="/"[^>]*>\s*nParity', home)
    assert nav(home) == ["Runs", "New run"]
    inside = nav(client.get(f"/runs/{run.id}").text)
    assert inside == ["Runs", "New run", "Findings", "Mapping"]
    assert "Run" not in inside


def test_static_and_404(setup):
    client, run = setup
    assert client.get("/static/nparity.css").status_code == 200
    assert client.get("/runs/nope").status_code == 404
    assert client.get(f"/runs/{run.id}/findings/f-999").status_code == 404
