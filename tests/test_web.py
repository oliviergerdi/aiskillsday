import html
import re
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.web import views
from nparity import pipeline, store
from nparity.config import load_thresholds
from nparity.models import FieldMap, Finding, HttpResult, Request, Run, Sample
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


def test_finding_links_to_its_review_controls_before_response_bodies(setup):
    client, run = setup
    for finding in run.findings[:2]:
        response = client.get(f"/runs/{run.id}/findings/{finding.id}")
        assert response.status_code == 200
        target = f"{finding.id}-review"
        assert response.text.index(f'href="#{target}"') < response.text.index("<pre>")
        assert f'class="decision" id="{target}"' in response.text


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
    legacy = run.model_copy(update={"id": "demo"})
    (app.state.runs_dir / "demo.yaml").write_text(legacy.model_dump_json(exclude={"contract", "coverage"}), encoding="utf-8")
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


def _finding(i, status):
    return Finding(id=f"f-{i}", endpoint="GET /x", path=f"$.f{i}", kind="changed", source="diff", status=status)


@pytest.mark.parametrize(("path", "before", "after", "old_line", "new_line", "fields"), [
    ("$.name",
     {"name": "Sea Serpent", "category": {"name": "Dogs"}},
     {"category": {"name": "Dogs"}, "name": "doggie", "tags": [{"name": "other"}]},
     '"name": "Sea Serpent"', '"name": "doggie"', []),
    ("$.items[id=2].name",
     {"items": [{"id": 2, "name": "old"}, {"id": 1, "name": "other"}]},
     {"items": [{"id": 1, "name": "other"}, {"id": 2, "name": "new"}]},
     '"name": "old"', '"name": "new"', []),
    ("$.items[1]", {"items": [10, 20]}, {"items": [10, 30]}, "20", "30", []),
    ("$.profile.name",
     {"customer": {"name": "old"}, "name": "unrelated"},
     {"profile": {"name": "new"}, "name": "unrelated"},
     '"name": "old"', '"name": "new"',
     [FieldMap(endpoint="GET /x", old="customer", new="profile", source="rule", status="accepted")]),
])
def test_finding_highlights_only_the_reported_path(path, before, after, old_line, new_line, fields):
    request = Request(method="GET", path="/x")
    sample = Sample(old_request=request, new_request=request,
                    old=HttpResult(status=200, body=before), new=HttpResult(status=200, body=after))
    finding = Finding(id="finding", endpoint=request.endpoint, path=path, kind="changed",
                      source="diff", samples=[sample], differs_in=[0])
    run = Run(id="paths", started_at=datetime.now(timezone.utc), fields=fields)
    view = views.finding_view(run, finding, load_thresholds())

    assert [line.text.strip().rstrip(",") for line in view.old_lines if line.hl] == [old_line]
    assert [line.text.strip().rstrip(",") for line in view.new_lines if line.hl] == [new_line]


@pytest.mark.parametrize(("path", "kind", "old_line", "new_line", "new_note"), [
    ("$[*].tags[*]", "type_changed", "{", '"unexpected"', ""),
    ("$[*].name", "missing_in_new", '"name": "old"', "{", 'Missing field "name"'),
])
def test_report_highlights_array_shape_evidence(tmp_path, path, kind, old_line, new_line, new_note):
    request = Request(method="GET", path="/x")
    sample = Sample(
        old_request=request, new_request=request,
        old=HttpResult(status=200, body=[{"id": 1, "name": "old", "tags": [{"id": 1}]}]),
        new=HttpResult(status=200, body=[
            {"id": 2, "name": "new", "tags": [{"id": 2}, "unexpected"]},
            {"id": 3, "tags": [{"id": 3}]},
        ]),
    )
    finding = Finding(id="f-1", endpoint=request.endpoint, path=path, kind=kind, status="unsure",
                      source="diff", samples=[sample], differing=1, differs_in=[0])
    run = Run(id="array-shape", started_at=datetime.now(timezone.utc), findings=[finding],
              config={"independent_data": True})
    store.save(run, tmp_path)
    previous = app.state.runs_dir, app.state.ledger_path
    app.state.runs_dir, app.state.ledger_path = tmp_path, tmp_path / "accepted.yaml"
    try:
        response = TestClient(app).get(f"/runs/{run.id}/findings/{finding.id}")
    finally:
        app.state.runs_dir, app.state.ledger_path = previous
    assert response.status_code == 200
    for side, line, note in (("old", old_line, "Before example"), ("new", new_line, new_note)):
        highlighted = re.findall(rf'<span[^>]*class="hl-{side}"[^>]*>(.*?)</span>', response.text)
        assert len(highlighted) == 1
        assert html.unescape(highlighted[0]).strip().startswith(line)
        assert note in html.unescape(highlighted[0])
        assert f'href="#f-1-{side}-highlight"' in response.text
        assert f'id="f-1-{side}-highlight"' in response.text


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


def test_static_files_are_revalidated(setup):
    client, _ = setup
    for path in ("/static/nparity.css", "/static/htmx.min.js"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-cache", path


def test_run_name_and_backend_label():
    assert views.run_name("2026-11-26T124642-petstore-4676e543c67a") == "petstore"
    assert views.run_name("demo") == "demo"
    assert views.backend_label("fake") == "Fake" and views.backend_label("gemini-2.5-flash") == "Flash"
