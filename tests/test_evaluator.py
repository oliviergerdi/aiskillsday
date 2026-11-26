import pytest

from nparity.evaluator.base import Answer, Choice, build, confidence, one_hot
from nparity.evaluator.cache import Cached
from nparity.evaluator.fake import FakeBackend


@pytest.fixture(scope="module")
def fake():
    return FakeBackend.from_file("fixtures/answer_key.yaml")


def q(qid, *keys, instructions="pick one"):
    return Choice(id=qid, instructions=instructions, criteria={k: f"desc {k}" for k in keys})


def test_fake_endpoint_mapping(fake):
    qid = "map:endpoint:GET /customers/{id}"
    a = fake.evaluate("s", [q(qid, "GET /orders/{id}", "GET /clients/{clientId}", "none")])[qid]
    assert a.value == "GET /clients/{clientId}"
    assert a.p_winner == 1.0 and not a.off_list


def test_fake_field_mapping_and_drop(fake):
    a = fake.evaluate("s", [q("map:field:GET /customers/{id}:fullName", "name", "none"),
                            q("map:field:GET /customers/{id}:legacyCode", "name", "none")])
    assert a["map:field:GET /customers/{id}:fullName"].value == "name"
    assert a["map:field:GET /customers/{id}:legacyCode"].value == "none"


def test_fake_triage(fake):
    qid = "triage:GET /orders/{id}:$.total"
    a = fake.evaluate("s", [q(qid, "intended", "regression", "unsure")], reasons=True)[qid]
    assert a.value == "regression" and a.reason


def test_fake_triage_ignores_noise_rows(fake):
    # GET /orders $.items is both noise (#1) and regression (#7): triage must get the regression
    qid = "triage:GET /orders:$.items"
    assert fake.evaluate("s", [q(qid, "intended", "regression", "unsure")])[qid].value == "regression"


def test_fake_unknown_is_uniform_off_list(fake):
    a = fake.evaluate("s", [q("triage:GET /nope:$.x", "intended", "regression", "unsure")])["triage:GET /nope:$.x"]
    assert a.off_list
    assert a.p_winner == pytest.approx(1 / 3)


def test_confidence():
    assert confidence({"a": 1.0, "b": 0.0}) == 1.0
    assert confidence({"a": 0.5, "b": 0.5}) == pytest.approx(0.0)


class Counting:
    id = "counting"
    max_options = 5

    def __init__(self):
        self.calls = 0

    def evaluate(self, state, questions, reasons=False):
        self.calls += 1
        return {x.id: one_hot(next(iter(x.criteria)), list(x.criteria)) for x in questions}


def test_cache_hits_and_misses(tmp_path):
    inner = Counting()
    c = Cached(inner, tmp_path)
    c.evaluate({"s": 1}, [q("a", "x", "y")])
    second = c.evaluate({"s": 1}, [q("a", "x", "y")])
    assert inner.calls == 1
    assert second["a"].meta["cached"] is True
    assert isinstance(second["a"], Answer)
    c.evaluate({"s": 1}, [q("a", "x", "y", instructions="changed")])
    assert inner.calls == 2
    c.evaluate({"s": 2}, [q("a", "x", "y")])
    assert inner.calls == 3
    assert len(list(tmp_path.glob("*.yaml"))) == 3


def test_build_defaults_to_fake(monkeypatch):
    monkeypatch.delenv("NPARITY_LLM", raising=False)
    assert build().id == "fake"
