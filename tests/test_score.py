from datetime import UTC, datetime

from nparity.models import AnswerKey, Finding, Noise, Run
from nparity.score import score


def f(endpoint, path, label, status="shown"):
    return Finding(id="x", endpoint=endpoint, path=path, kind="changed", source="diff", label=label, status=status)


def run(findings, noise=()):
    return Run(id="r", started_at=datetime(2026, 11, 26, tzinfo=UTC), findings=findings, noise=list(noise))


KEY = AnswerKey(findings=[
    {"n": 1, "endpoint": "GET /orders", "path": "$.items", "expect": "noise"},
    {"n": 7, "endpoint": "GET /orders", "path": "$.items", "expect": "regression"},
    {"n": 2, "endpoint": "POST /orders", "path": "$.id", "expect": "noise"},
    {"n": 9, "endpoint": "GET /orders/{id}", "path": "$.detail", "expect": "unsure"},
])


def test_noise_and_findings_kept_apart():
    """Review focus 4: exact path matching; noise keys only match Noise records."""
    r = run([f("GET /orders", "$.items", "regression"), f("GET /orders/{id}", "$.detail", "unsure", "unsure")],
            [Noise(endpoint="GET /orders", path="$.items", rule="unordered"),
             Noise(endpoint="POST /orders", path="$.id", rule="mask")])
    s = score(r, KEY)
    assert (s.correct, s.total, s.unsure, s.false_regressions) == (4, 4, 1, 0)


def test_exact_path_only():
    r = run([f("GET /orders", "$.items[0].id", "regression")])
    s = score(r, KEY)
    got = {d["n"]: d["got"] for d in s.details}
    assert got[7] == "missing" and got[1] == "missing"


def test_false_regression_counted():
    r = run([f("GET /orders/{id}", "$.detail", "regression")])
    s = score(r, KEY)
    assert s.false_regressions == 1
