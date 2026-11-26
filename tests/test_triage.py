import threading

import pytest

from nparity.config import load_thresholds
from nparity.evaluator.base import Answer
from nparity.evaluator.fake import FakeBackend
from nparity.models import Finding, HttpResult, Request, Sample, Telemetry
from nparity.triage import state_for, triage

TH = load_thresholds()


def finding(endpoint, path, kind="changed", source="diff"):
    req = Request(method="GET", path="/orders/{id}", params={"id": 2})
    s = Sample(old_request=req, new_request=req, old=HttpResult(status=200, body={"total": 10.01}),
               new=HttpResult(status=200, body={"total": 10.0}))
    return Finding(id="f", endpoint=endpoint, path=path, kind=kind, source=source, samples=[s],
                   differing=1, differs_in=[0])


class Fixed:
    """Always answers `value` with probability `p`; records which calls asked for reasons."""
    id = "fixed"
    max_options = 5

    def __init__(self, value, p):
        self.value, self.p = value, p
        self.reason_calls = []
        self.lock = threading.Lock()

    def evaluate(self, state, questions, reasons=False):
        out = {}
        for q in questions:
            rest = (1 - self.p) / (len(q.criteria) - 1)
            probs = {k: (self.p if k == self.value else rest) for k in q.criteria}
            if reasons:
                with self.lock:
                    self.reason_calls.append(q.id)
            out[q.id] = Answer(value=self.value, probabilities=probs, p_winner=self.p, confidence=0.5,
                               reason="because" if reasons else None)
        return out


def test_fake_labels():
    fake = FakeBackend.from_file("fixtures/answer_key.yaml")
    fs = triage([finding("GET /orders/{id}", "$.total"), finding("POST /orders", "status", "status_changed"),
                 finding("GET /orders/{id}", "$.detail")], "intent", fake, TH, workers=1)
    assert [(f.label, f.status) for f in fs] == [("regression", "shown"), ("intended", "accepted"),
                                                 ("unsure", "unsure")]
    assert fs[0].reason and fs[1].reason is None


def test_intended_below_bar_becomes_unsure():
    (f,) = triage([finding("E", "$.x")], "intent", Fixed("intended", 0.62), TH)
    assert (f.label, f.status, f.p) == ("unsure", "unsure", 0.62)
    assert f.probabilities["intended"] == pytest.approx(0.62)


def test_confident_regression_shown():
    (f,) = triage([finding("E", "$.x")], "intent", Fixed("regression", 0.9999), TH)
    assert (f.label, f.status) == ("regression", "shown")


def test_low_confidence_regression_goes_to_a_human():
    """Symmetric bar: #9 came back regression at 0.9895 against >=0.99999 for real regressions."""
    (f,) = triage([finding("E", "$.x")], "intent", Fixed("regression", 0.9895), TH)
    assert (f.label, f.status, f.type_info["leans"]) == ("unsure", "unsure", "regression")
    assert f.reason                                      # still explained, still on screen


def test_reasons_only_for_shown_and_unsure():
    ev = Fixed("intended", 0.99)
    triage([finding("E", "$.a"), finding("E", "$.b")], "intent", ev, TH)
    assert ev.reason_calls == []
    ev2 = Fixed("regression", 0.99)
    tel = Telemetry()
    triage([finding("E", "$.a")], "intent", ev2, TH, tel)
    assert ev2.reason_calls == ["triage:E:$.a"]
    assert tel.llm_calls == 2 and tel.reasons == 1


def test_state_is_plain_text_intent_first():
    st = state_for(finding("GET /orders/{id}", "$.total"), "the note")
    assert st.startswith("Intent note")
    assert '"""\nthe note\n"""' in st
    assert "Where: response field `total`" in st
    assert "- GET /orders/{id} {'id': 2}: old 10.01 → new 10.0" in st
    assert "Seen in: 1 of 1 sampled requests" in st


def test_state_for_rename_shows_new_value():
    req = Request(method="GET", path="/customers/{id}", params={"id": 1})
    s = Sample(old_request=req, new_request=req, old=HttpResult(status=200, body={"fullName": "Ada"}),
               new=HttpResult(status=200, body={"name": "Ada"}))
    f = Finding(id="f", endpoint="GET /customers/{id}", path="$.fullName", kind="renamed", source="mapping",
                samples=[s], type_info={"mapping": "fullName → name (llm)", "new_field": "name"})
    st = state_for(f, "renames fullName to name")
    assert "now called `name`" in st
    assert "old 'Ada' → new 'Ada'" in st and "absent" not in st


def test_llm_error_is_flagged_not_hidden():
    from nparity.triage import apply
    f = finding("E", "$.x")
    apply(f, Answer(value="intended", probabilities={"intended": 1 / 3}, p_winner=1 / 3, confidence=0,
                    off_list=True, meta={"error": "ConnectError"}), TH)
    assert f.status == "unsure" and "LLM error" in f.reason
