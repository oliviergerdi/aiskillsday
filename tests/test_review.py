from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from nparity import pipeline
from nparity.retry import RetryPolicy
from nparity.review import (Ledger, compare, finding_key, latest_baseline, open_counts, review_states, scope_of,
                            stale, verdict)


def toy_run():
    return pipeline.run(pipeline.RunConfig(old="http://testserver/v1", new="http://testserver/v2", workers=1,
                                           retry=RetryPolicy(base=0.0)), TestClient(app))


@pytest.fixture(scope="module")
def runs():
    a, b = toy_run(), toy_run()
    return a, b.model_copy(update={"id": b.id + "-b"})   # same-second runs share an id; keep them distinct


@pytest.fixture
def ledger(tmp_path):
    return Ledger.load(tmp_path / "accepted.yaml")


def by_path(run, path):
    return next(f for f in run.findings if f.path == path)


def test_keys_stable_across_runs(runs):
    """Review focus 1."""
    a, b = runs
    assert {finding_key(f) for f in a.findings} == {finding_key(f) for f in b.findings}
    assert finding_key(by_path(a, "$.total")) == "GET /orders/{id} -> GET /orders/{id} | $.total | changed"


def test_scope(runs):
    run = runs[0]
    assert scope_of(run) == "http://testserver/v1 -> http://testserver/v2"
    assert scope_of(run.model_copy(update={"config": {**run.config, "config": "toy"}})) == "toy"


def test_record_replace_remove_round_trip(runs, ledger):
    run = runs[0]
    f = by_path(run, "$.detail")
    ledger.record(run, f, "accept", "Temba", "wording agreed")
    ledger.record(run, f, "reject", " Gerdi ")
    assert len(ledger.entries) == 1
    loaded = Ledger.load(ledger.path)
    e = loaded.entries[0]
    assert (e.decision, e.by, e.run, e.model_label, e.model_p) == ("reject", "Gerdi", run.id, f.label, f.p)
    assert loaded.remove(e.scope, e.key) and Ledger.load(ledger.path).entries == []
    assert not loaded.remove(e.scope, e.key)


def test_empty_name_rejected(runs, ledger):
    with pytest.raises(ValueError):
        ledger.record(runs[0], runs[0].findings[0], "accept", "  ")


def test_state_table(runs, ledger):
    run = runs[0]
    st = review_states(run, ledger)
    assert st[by_path(run, "$.total").id][0] == "needs_review"          # shown regression
    assert st[by_path(run, "$.detail").id][0] == "needs_review"         # unsure
    assert st[by_path(run, "status").id][0] == "intended_model"         # model-accepted
    ledger.record(run, by_path(run, "$.total"), "accept", "T")
    ledger.record(run, by_path(run, "status"), "reject", "T")           # review focus 2
    st = review_states(run, ledger)
    assert st[by_path(run, "$.total").id][0] == "accepted"
    assert st[by_path(run, "status").id][0] == "rejected"
    assert open_counts(run, ledger)["rejected"] == 1


def test_verdict(runs, ledger):
    run = runs[0]
    assert verdict(run, ledger) == ("4 open items: 0 confirmed regressions, 4 need review", "reg")
    for f in run.findings:
        if f.status in ("shown", "unsure"):
            ledger.record(run, f, "accept", "T")
    assert verdict(run, ledger) == ("Ready to cut over", "int")
    limited = run.model_copy(update={"config": {**run.config, "limited_comparison": True}})
    assert verdict(limited, ledger) == ("No open items in the sampled responses", "uns")
    ledger.record(run, by_path(run, "$.total"), "reject", "T")
    assert verdict(run, ledger) == ("1 open item: 1 confirmed regression, 0 need review", "reg")
    errored = run.model_copy(update={"errors": [run.findings[0]]})
    assert "1 error" in verdict(errored, ledger)[0]


def test_scopes_do_not_leak(runs, ledger):
    """Review focus 4."""
    run = runs[0]
    ledger.record(run.model_copy(update={"config": {**run.config, "config": "toy"}}),
                  by_path(run, "$.total"), "accept", "T")
    other = run.model_copy(update={"config": {**run.config, "config": "petstore"}})
    assert review_states(other, ledger)[by_path(run, "$.total").id][0] == "needs_review"


def test_stale(runs, ledger):
    run = runs[0]
    ledger.record(run, by_path(run, "$.total"), "accept", "T")
    gone = run.model_copy(update={"findings": [f for f in run.findings if f.path != "$.total"]})
    assert [e.path for e in stale(gone, ledger)] == ["$.total"]
    assert stale(run, ledger) == []


def test_compare(runs):
    a, b = runs
    c = compare(b, a)
    assert c.counts == {"new": 0, "unchanged": 8, "resolved": 0}
    fewer = b.model_copy(update={"findings": [f for f in b.findings if f.path != "$.total"]})
    assert compare(fewer, a).counts == {"new": 0, "unchanged": 7, "resolved": 1}
    assert compare(b, fewer).counts["new"] == 1


def test_latest_baseline(runs):
    """Review focus 3."""
    a, b = runs
    later = b.model_copy(update={"id": "later", "started_at": b.started_at + timedelta(hours=1)})
    other = a.model_copy(update={"id": "other", "config": {**a.config, "config": "petstore"},
                                 "started_at": a.started_at + timedelta(minutes=1)})
    pool = [a, b, later, other]
    assert latest_baseline(b, pool).id == a.id                      # never itself, never later, never other scope
    assert latest_baseline(later, pool).id == b.id
    assert latest_baseline(a, pool) is None
    assert latest_baseline(scope_of(a), pool).id == "later"


def test_agreement_table(runs, ledger):
    """Review focus 3: a missed regression has its own count."""
    from nparity.review import agreement
    run = runs[0]
    assert agreement(run, ledger).decided == 0 and agreement(run, ledger).undecided == 8
    ledger.record(run, by_path(run, "$.total"), "reject", "T")        # model regression -> agree
    ledger.record(run, by_path(run, "$.currency"), "accept", "T")     # model regression -> false regression
    ledger.record(run, by_path(run, "status"), "reject", "T")         # model intended -> missed regression
    ledger.record(run, by_path(run, "$.legacyCode"), "accept", "T")   # model intended -> agree
    ledger.record(run, by_path(run, "$.detail"), "accept", "T")       # model unsure
    a = agreement(run, ledger)
    assert (a.decided, a.agree, a.false_regressions, a.missed_regressions, a.model_unsure, a.undecided) == \
        (5, 2, 1, 1, 1, 3)
    assert a.text.startswith("Agreement with reviewers: 2/4 decided · 1 false regressions · 1 missed")
