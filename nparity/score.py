"""Score a run against the answer key."""

from __future__ import annotations

from nparity.models import AnswerKey, Run, Score


def score(run: Run, key: AnswerKey) -> Score:
    """`expect: noise` keys match only Noise records; all others match only findings. Both on exact
    (endpoint, path): items 1 and 7 share GET /orders + $.items, this split keeps them apart."""
    findings = {(f.endpoint, f.path): f for f in run.findings}
    noise = {(n.endpoint, n.path) for n in run.noise}
    details = []
    correct = false_regressions = 0
    for item in key.findings:
        k = (item["endpoint"], item["path"])
        expect = item["expect"]
        if expect == "noise":
            got = "noise" if k in noise else "missing"
        else:
            f = findings.get(k)
            got = (f.label or "unlabelled") if f else "missing"
        ok = got == expect
        correct += ok
        if got == "regression" and expect != "regression":
            false_regressions += 1
        details.append({"n": item.get("n"), "endpoint": k[0], "path": k[1], "expect": expect, "got": got, "ok": ok})
    return Score(correct=correct, total=len(key.findings),
                 unsure=sum(f.status == "unsure" for f in run.findings),
                 false_regressions=false_regressions, details=details)
