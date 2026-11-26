import pytest
from fastapi.testclient import TestClient

from app.main import app
from nparity.config import Threshold, load_thresholds
from nparity.evaluator.base import Choice, TooManyOptions, one_hot
from nparity.evaluator.fake import FakeBackend
from nparity.map import map_endpoints, map_fields, stems, status_for
from nparity.models import Telemetry
from nparity.openapi import endpoints, load_spec


@pytest.fixture(scope="module")
def specs():
    c = TestClient(app)
    return (endpoints(load_spec(c, "http://testserver/v1")),
            endpoints(load_spec(c, "http://testserver/v2")))


@pytest.fixture(scope="module")
def fake():
    return FakeBackend.from_file("fixtures/answer_key.yaml")


@pytest.fixture(scope="module")
def th():
    return load_thresholds()


def by_old(maps):
    return {m.old: m for m in maps}


def test_stems():
    assert stems("/customers/{id}") == {"customer"}
    assert stems("/clients/{clientId}") == {"client"}
    assert stems("/orders") == {"order"}


def test_endpoints_rules_and_llm(specs, fake, th):
    v1, v2 = specs
    tel = Telemetry()
    m = by_old(map_endpoints(v1, v2, fake, th, tel))
    for k in ("GET /orders", "POST /orders", "GET /orders/{id}"):
        assert (m[k].new, m[k].source, m[k].status) == (k, "rule", "accepted")
    c = m["GET /customers/{id}"]
    assert (c.new, c.source, c.status, c.p) == ("GET /clients/{clientId}", "llm", "accepted", 1.0)
    assert tel.rule_decisions == 3 and tel.llm_calls == 1


class Capture:
    id = "capture"
    max_options = 30

    def __init__(self):
        self.questions: list[Choice] = []

    def evaluate(self, state, questions, reasons=False):
        self.questions += questions
        return {q.id: one_hot("none", list(q.criteria)) for q in questions}


def test_widened_question_has_all_same_method_and_none(specs, th):
    v1, v2 = specs
    cap = Capture()
    m = by_old(map_endpoints([e for e in v1 if e.key == "GET /customers/{id}"], v2, cap, th))
    (q,) = cap.questions
    assert set(q.criteria) == {"GET /orders", "GET /orders/{id}", "GET /clients/{clientId}", "none"}
    assert "best match" in q.instructions
    assert m["GET /customers/{id}"].new is None and m["GET /customers/{id}"].status == "unmapped"


def test_too_many_options(specs, th):
    v1, v2 = specs
    cap = Capture()
    cap.max_options = 2
    with pytest.raises(TooManyOptions):
        map_endpoints([e for e in v1 if e.key == "GET /customers/{id}"], v2, cap, th)


def test_fields(specs, fake, th):
    v1, v2 = specs
    o = next(e for e in v1 if e.key == "GET /customers/{id}")
    n = next(e for e in v2 if e.key == "GET /clients/{clientId}")
    fm = {f.old: f for f in map_fields([(o, n)], fake, th)}
    for name in ("id", "email", "type", "currency"):
        assert (fm[name].new, fm[name].source) == (name, "rule")
    assert (fm["fullName"].new, fm["fullName"].source, fm["fullName"].status) == ("name", "llm", "accepted")
    assert (fm["legacyCode"].new, fm["legacyCode"].source, fm["legacyCode"].status) == (None, "llm", "accepted")


@pytest.mark.parametrize("p,censored,want", [
    (0.96, False, "accepted"), (0.95, False, "accepted"), (0.6, False, "review"),
    (0.3, False, "unmapped"), (0.99, True, "review"), (None, False, "unmapped"),
])
def test_status_for(p, censored, want):
    assert status_for(p, censored, Threshold(auto_accept=0.95, needs_review=0.5)) == want


def test_thresholds_loaded(th):
    assert th.mapping.auto_accept == 0.95
    assert th.triage_intended.auto_accept == 0.98
    assert th.triage_regression.auto_accept == 0.999


class Failing:
    id = "failing"
    max_options = 30

    def evaluate(self, state, questions, reasons=False):
        from nparity.evaluator.base import uniform
        return {q.id: uniform(list(q.criteria), meta={"error": "ConnectError: boom"}) for q in questions}


def test_llm_error_is_marked_not_silently_unmapped(specs, th):
    v1, v2 = specs
    m = by_old(map_endpoints(v1, v2, Failing(), th))
    c = m["GET /customers/{id}"]
    assert (c.new, c.status, c.error) == (None, "unmapped", "ConnectError: boom")
    assert m["GET /orders"].error is None          # rule decisions never call the LLM
