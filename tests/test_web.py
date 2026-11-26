import html
import re
from types import SimpleNamespace
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


def _grouped_run(run_id, specs):
    """specs: (endpoint, new_endpoint, status, p) per finding; ids are f-1, f-2, ... in order."""
    findings = [Finding(id=f"f-{i}", endpoint=ep, new_endpoint=new, path=f"$.x{i}", kind="changed", source="diff",
                        label="regression", p=p, status=st)
                for i, (ep, new, st, p) in enumerate(specs, 1)]
    run = Run(id=run_id, started_at=datetime.now(timezone.utc), findings=findings,
              config={"old": "http://a", "new": "http://b", "backend": "x", "requests": 1, "endpoints": 2})
    store.save(run, app.state.runs_dir)
    return run


def _section(page, title):
    """HTML of the section whose h2 contains `title`, up to the next h2."""
    start = page.index(f">{title}</span>")
    end = page.find("<h2", start)
    return page[start:end if end != -1 else len(page)]


def _group_headers(section):
    """(opening tag, header text without markup) for each group in a section."""
    return [(tag, re.sub(r"<[^>]+>|\s+", " ", head))
            for tag, head in re.findall(r'(<details class="g"[^>]*>)\s*<summary[^>]*>(.*?)</summary>', section, re.S)]


def test_two_groups(setup):
    client, _ = setup
    run = _grouped_run("grp-two", [("GET /a", "GET /a2", "shown", 0.5), ("GET /a", "GET /a2", "shown", 0.6),
                                   ("GET /b", "GET /b2", "shown", 0.7)])
    reg = _section(client.get(f"/runs/{run.id}").text, "Regressions")
    assert reg.count('<details class="g"') == 2
    assert "2 groups" in reg[:reg.index('<div class="findings">')]


def test_group_header_count_and_min_p(setup):
    client, _ = setup
    run = _grouped_run("grp-hdr", [("GET /a", "GET /a2", "shown", 0.910), ("GET /a", "GET /a2", "shown", 0.357),
                                   ("GET /b", "GET /b2", "shown", 0.640)])
    head = next(h for _, h in _group_headers(_section(client.get(f"/runs/{run.id}").text, "Regressions"))
                if "GET /a2" in h)
    assert re.search(r"\b2\b", head)
    assert "0.357" in head and "0.910" not in head


def test_group_rows_same_hx(setup):
    client, _ = setup
    run = _grouped_run("grp-hx", [("GET /a", "GET /a2", "shown", 0.5), ("GET /a", "GET /a2", "shown", 0.6),
                                  ("GET /b", "GET /b2", "shown", 0.7)])
    page = client.get(f"/runs/{run.id}").text
    assert page.count('<details class="f"') == 3
    pre_opened = [f for f in run.findings if f"/findings/{f.id}\"" not in page]
    assert len(pre_opened) == 1                      # exactly the first regression is rendered server-side
    for f in run.findings:
        if f is not pre_opened[0]:
            assert f'hx-get="/runs/{run.id}/findings/{f.id}"' in page
    partial = client.get(f"/runs/{run.id}/findings/{run.findings[1].id}")
    assert partial.status_code == 200 and "<details" not in partial.text


def test_group_counts_sum(setup):
    client, _ = setup
    run = _grouped_run("grp-sum", [
        ("GET /a", "GET /a2", "shown", 0.5), ("GET /a", "GET /a2", "shown", 0.6), ("GET /b", "GET /b2", "shown", 0.7),
        ("GET /a", "GET /a2", "unsure", 0.4), ("GET /c", "GET /c2", "unsure", 0.3),
        ("GET /d", "GET /d2", "accepted", 0.95), ("GET /d", "GET /d2", "accepted", 0.96),
        ("GET /d", "GET /d2", "accepted", 0.97)])
    page = client.get(f"/runs/{run.id}").text
    assert page.index("Regressions</span>") < page.index("Unsure</span>") < page.index("Intended</span>")
    assert "always shown, never auto-dismissed" in page
    for title, n in (("Regressions", 3), ("Unsure", 2), ("Intended", 3)):
        sec = _section(page, title)
        groups = sec.split('<details class="g"')[1:]
        assert sum(g.count('<details class="f"') for g in groups) == n == sec.count('<details class="f"')
        for g in groups:                              # header count matches the rows nested in the group
            rows = g.count('<details class="f"')
            assert re.search(rf"\b{rows}\b", re.sub(r"<[^>]+>", " ", g.split("</summary>")[0]))


def test_group_collapse_rule(setup):
    client, _ = setup
    specs = [("GET /r", "GET /r2", "shown", 0.1 + i / 100) for i in range(4)]
    specs += [("GET /s", "GET /s2", "shown", 0.9 + i / 100) for i in range(4)]
    specs += [("GET /big", "GET /big2", "unsure", 0.2 + i / 100) for i in range(4)]
    specs += [("GET /small", "GET /small2", "unsure", 0.5 + i / 100) for i in range(3)]
    run = _grouped_run("grp-open", specs)
    page = client.get(f"/runs/{run.id}").text
    reg = _group_headers(_section(page, "Regressions"))
    assert " open" in reg[0][0]                       # first regression group open even with 4 findings
    assert " open" not in reg[1][0]                   # a later group with 4 is collapsed
    uns = {h: tag for tag, h in _group_headers(_section(page, "Unsure"))}
    assert " open" not in next(t for h, t in uns.items() if "GET /big2" in h)
    assert " open" in next(t for h, t in uns.items() if "GET /small2" in h)


def test_group_order():
    def view(ep, p):
        return SimpleNamespace(f=Finding(id="x", endpoint=ep, new_endpoint=ep + "2", path="$", kind="changed",
                                         source="diff", p=p))
    vs = [view("X", 0.2), view("Y", 0.1), view("Z", 0.3), view("Z", 0.1), view("Z", 0.5), view("N", None)]
    groups = views.group_findings(vs)
    assert [g.endpoint for g in groups] == ["Z", "Y", "X", "N"]   # min p asc, ties by count desc, None last
    assert [g.count for g in groups] == [3, 1, 1, 1]
    assert [g.min_p for g in groups] == [0.1, 0.1, 0.2, None]
    assert groups[0].new_endpoint == "Z2" and len(groups[0].items) == 3


def test_static_and_404(setup):
    client, run = setup
    assert client.get("/static/nparity.css").status_code == 200
    assert client.get("/runs/nope").status_code == 404
    assert client.get(f"/runs/{run.id}/findings/f-999").status_code == 404
