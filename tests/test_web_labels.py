"""UX-3: plain labels instead of internal jargon on run, finding and mapping pages."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.web import views
from nparity import pipeline, store
from nparity.config import load_thresholds
from nparity.retry import RetryPolicy

TEMPLATES = Path(__file__).parent.parent / "app" / "web" / "templates"
LEGEND = "Bar = confidence in the label. Line = confidence needed to accept without review."


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


def _th(run):
    return load_thresholds(backend_id=run.config.get("backend"))


def test_templates_have_no_jargon():
    banned = ("p(winner)", "Observed type", "Declared type", "Distribution:", "Runners-up")
    for t in TEMPLATES.rglob("*"):
        if t.is_file():
            text = t.read_text()
            for s in banned:
                assert s not in text, f"{s!r} in {t.name}"


def test_finding_partial_uses_plain_labels(setup):
    client, run = setup
    f = next(f for f in run.findings if f.probabilities)
    html = client.get(f"/runs/{run.id}/findings/{f.id}").text
    assert "Confidence" in html
    assert "Type seen in responses" in html
    assert "Model's split between labels" in html


def test_mapping_page_uses_plain_labels_and_model_badge(setup):
    client, run = setup
    html = client.get(f"/runs/{run.id}/mapping").text
    for s in ("Confidence", "Type in the spec", "Next best matches"):
        assert s in html, s
    assert ">model<" in html
    assert ">llm<" not in html


def test_threshold_text_is_percentage(setup):
    _, run = setup
    th = _th(run)
    f = next(f for f in run.findings if (f.label or "unsure") in ("regression", "intended"))
    text = views.finding_view(run, f, th).threshold_text
    assert re.search(r"^\d+(\.\d+)?% needed to (confirm as a regression|accept as intended)$", text), text
    assert not re.search(r"\d\.\d{3}", text), text


def test_legend_appears_once_on_run_page(setup):
    client, run = setup
    assert client.get(f"/runs/{run.id}").text.count(LEGEND) == 1


def test_row_summary_shows_percent_with_raw_value_in_tooltip(setup):
    client, run = setup
    page = client.get(f"/runs/{run.id}").text
    texts = re.findall(r'class="pbar"[^>]*>.*?</div></div>([^<]*)</div>', page, re.S)
    assert texts, "no pbar rows found"
    for t in texts:
        t = t.strip()
        assert t.endswith("%") or t == "—", t
    for f in run.findings:
        if f.p is not None:
            assert f'title="{f.p:.3f}"' in page, f.p


def test_conf_text_percent():
    from nparity.models import Finding
    th = load_thresholds(backend_id=None)
    for p, want in ((0.999, "99.9%"), (1.0, "100%"), (0.9996, "99.9%"), (0.5, "50%")):
        f = Finding(id="x", endpoint="GET /a", path="$.a", kind="changed", source="diff", p=p, label="regression")
        v = views.finding_view(None, f, th)    # no samples, so run is never read
        assert v.conf_text == want
        assert v.p_text == f"{p:.3f}"


def _threshold_text(label):
    from nparity.models import Finding
    th = load_thresholds(backend_id=None)
    f = Finding(id="x", endpoint="GET /a", path="$.a", kind="changed", source="diff", p=0.5, label=label)
    return views.finding_view(None, f, th).threshold_text


def test_threshold_text_regression_bar_wording():
    assert _threshold_text("regression") == "99.9% needed to confirm as a regression"


def test_threshold_text_intended_bar_wording():
    assert _threshold_text("intended") == "98% needed to accept as intended"
