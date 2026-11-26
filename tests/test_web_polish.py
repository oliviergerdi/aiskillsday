"""UX-9: small UI polish (run names, group rows, dark selects, nav, scroll to progress)."""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.web import views
from app.web.routes import TEMPLATES
from nparity import pipeline, store
from nparity.retry import RetryPolicy

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app/web/static/nparity.css").read_text()
JS = (ROOT / "app/web/static/new-run.js").read_text()
MEDIA = "@media (max-width: 760px)"


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


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def _mobile_and_rest():
    start = CSS.index(MEDIA)
    open_ = CSS.index("{", start)
    depth, i = 0, open_
    while True:
        depth += CSS[i] == "{"
        depth -= CSS[i] == "}"
        if depth == 0:
            break
        i += 1
    return CSS[open_ + 1 : i], CSS[:start] + CSS[i + 1 :]


def _rules(css):
    return [([s.strip() for s in sel.split(",")], d) for sel, d in re.findall(r"([^{}]+)\{([^}]*)\}", css)]


def _render_row(in_group, **over):
    f = SimpleNamespace(id="f1", endpoint="GET /store/inventory", new_endpoint="GET /store/stock",
                        path="$.count", reason="because")
    v = SimpleNamespace(f=f, body_html="<p>x</p>", baseline_status="new",
                        entry=SimpleNamespace(decision="accept", by="ann"), kind_text="changed",
                        p_text="0.900", p_pct=90, color="#000", thr_pct=50, conf_text="90%")
    for k, val in over.items():
        setattr(v, k, val)
    ctx = {"run": SimpleNamespace(id="r1"), "v": v}
    if in_group:
        ctx["in_group"] = True
    return TEMPLATES.env.get_template("_row.html").render(**ctx)


def _f_ep(html):
    return re.search(r'<div class="f-ep">(.*?)</div>', html, re.S).group(1)


# 1. run_name
def test_run_name_without_hash_suffix():
    assert views.run_name("2026-11-26T124434-toy") == "toy"


def test_run_name_with_hash_suffix():
    assert views.run_name("2026-11-26T124642-petstore-4676e543c67a") == "petstore"


# 2. group rows
def test_group_row_does_not_repeat_group_endpoint(setup):
    client, run = setup
    page = client.get(f"/runs/{run.id}").text
    seen = 0
    for chunk in page.split('<details class="g"')[1:]:
        chunk = chunk.split("<h2")[0]
        pair = _text(re.search(r'<span class="g-ep">(.*?)</span>', chunk, re.S).group(1))
        endpoint = pair.split(" → ")[0]
        eps = re.findall(r'<details class="f"[^>]*>\s*<summary>\s*<div class="f-ep">(.*?)</div>', chunk, re.S)
        for ep in eps:
            seen += 1
            assert endpoint not in _text(ep), (pair, _text(ep))
    assert seen, "no rows found inside groups"


def test_group_row_keeps_f_ep_element(setup):
    client, run = setup
    page = client.get(f"/runs/{run.id}").text
    for chunk in page.split('<details class="g"')[1:]:
        chunk = chunk.split("<h2")[0]
        rows = chunk.count('<details class="f"')
        assert rows == len(re.findall(r'<details class="f"[^>]*>\s*<summary>\s*<div class="f-ep">', chunk))


def test_group_row_keeps_badges_in_f_ep():
    ep = _text(_f_ep(_render_row(in_group=True)))
    assert "new" in ep and "accepted · ann" in ep
    assert "GET /store/inventory" not in ep


def test_group_row_shows_unmapped_marker():
    f = SimpleNamespace(id="f1", endpoint="GET /a", new_endpoint=None, path="$.c", reason="")
    assert "→ unmapped" in _text(_f_ep(_render_row(in_group=True, f=f)))


def test_group_row_outside_group_keeps_endpoint():
    ep = _text(_f_ep(_render_row(in_group=False)))
    assert "GET /store/inventory" in ep and "→ GET /store/stock" in ep


def test_group_row_child_order_unchanged():
    html = _render_row(in_group=True)
    summary = re.search(r"<summary>(.*?)</summary>", html, re.S).group(1)
    classes = re.findall(r'<div class="(f-ep|f-path|f-kind|pbar|f-reason)"', summary)
    assert classes == ["f-ep", "f-path", "f-kind", "pbar", "f-reason"]


# 3. dark selects
def test_select_dark_color_scheme_on_root():
    root = re.search(r"^:root\s*\{([^}]*)\}", CSS, re.M).group(1)
    assert re.search(r"color-scheme:\s*light dark", root)


def test_select_dark_bare_select_rule_styled():
    _, rest = _mobile_and_rest()
    decls = [d for sels, d in _rules(rest) if "select" in sels]
    assert decls, "no bare `select` rule"
    for prop in ("background", "color", "border"):
        assert any(re.search(rf"(?<![-\w]){prop}(-color)?:[^;]*var\(--", d) for d in decls), prop


# 4. nav
def test_nav_nowrap_on_items():
    _, rest = _mobile_and_rest()
    assert any("nav.views a" in sels and "white-space: nowrap" in d for sels, d in _rules(rest))


def test_nav_nowrap_tightened_on_small_screens():
    mobile, _ = _mobile_and_rest()
    assert any(any("nav.views" in s for s in sels) and re.search(r"padding|gap", d) for sels, d in _rules(mobile))


# 5. scroll
def test_scroll_step_list_into_view_at_start():
    body = JS[JS.index("async function startJob"):]
    after = body[body.index("resetConsole();") + len("resetConsole();"):].lstrip()
    assert after.startswith("output.scrollIntoView("), after[:60]
    assert re.match(r'output\.scrollIntoView\(\{\s*block:\s*"start"', after), after[:60]


# 6. rerun selects fill their column
def _rerun_decls(selector):
    _, rest = _mobile_and_rest()
    return " ".join(d for sels, d in _rules(rest) if selector in sels)


def test_rerun_selects_fill_column():
    d = _rerun_decls(".rerun select")
    assert re.search(r"width:\s*100%", d), d
    assert re.search(r"min-width:\s*0", d), d
    assert re.search(r"padding:", d) and re.search(r"font:\s*inherit", d), d


def test_rerun_description_below_select():
    assert re.search(r"display:\s*block", _rerun_decls(".rerun small"))


def test_rerun_markup_has_select_then_description_in_each_field(setup):
    client, _ = setup
    html = client.get("/compare").text
    for sel_id in ("rerun-config", "rerun-baseline"):
        assert re.search(rf'<select id="{sel_id}"></select>\s*<small class="sub"', html), sel_id
