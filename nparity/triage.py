"""Triage each finding against the intent note: intended / regression / unsure (design section 6).

The state is plain text, intent note first, so the model compares a described change against the note
instead of decoding JSON paths. Template version is part of the cache key via the question text.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from nparity.config import Thresholds
from nparity.evaluator.base import Answer, Backend, Choice, tally
from nparity.jsonpath import MISSING, value_at
from nparity.lists import keys_text, membership
from nparity.models import Finding, Sample, Telemetry

TEMPLATE = "triage-v2"
CRITERIA = {
    "intended": "Intended: the intent note describes this change.",
    "regression": "Regression: the intent note does not describe this change.",
    "unsure": "Unsure: the intent note might cover it, but not clearly.",
}
INSTRUCTIONS = ("Compare the difference with the intent note. "
                "Which label fits this difference best?")
MAX_EXAMPLES = 3

WHAT = {
    "changed": "value changed", "missing_in_new": "field missing from the new response",
    "added_in_new": "new field added to the response", "status_changed": "HTTP status code changed",
    "list_length_changed": "number of items in the list changed", "type_changed": "value type changed",
    "items_removed": "list items present in the old response are missing from the new one",
    "items_added": "the new response's list has items the old one doesn't",
    "declared_type_changed": "declared schema type changed", "moved": "endpoint moved to a new path",
    "renamed": "field renamed", "dropped": "field no longer returned",
}


def question_id(f: Finding) -> str:
    return f"triage:{f.endpoint}:{f.path}"


def _show(v: Any) -> str:
    if v is MISSING:
        return "(absent)"
    if isinstance(v, list):
        return f"list of {len(v)} items"
    return repr(v) if isinstance(v, str) else str(v)


def _where(f: Finding) -> str:
    if f.path == "status":
        return "HTTP status code"
    if f.path == "endpoint":
        return "the endpoint path"
    if f.kind == "renamed":
        return f"response field `{f.path.removeprefix('$.')}`, now called `{f.type_info.get('new_field')}`"
    return f"response field `{f.path.removeprefix('$.')}`"


def _example(f: Finding, s: Sample) -> str:
    req = s.old_request
    call = f"{req.method} {req.path}" + (f" {req.params}" if req.params else "")
    if f.path == "status":
        old, new = s.old.status, s.new.status
    elif f.path == "endpoint":
        old, new = req.endpoint, s.new_request.endpoint if s.new_request else None
    elif f.kind == "renamed":
        old = _show(value_at(s.old.body, f.path))
        new = _show(value_at(s.new.body, f"$.{f.type_info.get('new_field')}"))
    elif f.kind in ("items_removed", "items_added"):
        a, b = value_at(s.old.body, f.path), value_at(s.new.body, f.path)
        m = membership(a, b)
        if m:
            k, removed, added = m
            keys = removed if f.kind == "items_removed" else added
            return (f"- {call}: old {len(a)} items → new {len(b)} items; only in "
                    f"{'old' if f.kind == 'items_removed' else 'new'}: {keys_text(k, keys)}")
        old, new = _show(a), _show(b)
    elif f.kind == "list_length_changed":
        a, b = value_at(s.old.body, f.path), value_at(s.new.body, f.path)
        old, new = (len(a) if isinstance(a, list) else _show(a)), (len(b) if isinstance(b, list) else _show(b))
        old, new = f"{old} items", f"{new} items"
    else:
        old, new = _show(value_at(s.old.body, f.path)), _show(value_at(s.new.body, f.path))
    return f"- {call}: old {old} → new {new}"


def state_for(f: Finding, intent: str) -> str:
    idx = f.differs_in or list(range(len(f.samples)))
    examples = [_example(f, f.samples[i]) for i in idx[:MAX_EXAMPLES] if i < len(f.samples)]
    lines = [
        "Intent note (the changes the rewrite was meant to make):",
        '"""', intent.strip(), '"""', "",
        "Difference found between the old and the new service:",
        f"Endpoint: {f.endpoint}" + (f" (new: {f.new_endpoint})" if f.new_endpoint and f.new_endpoint != f.endpoint else ""),
        f"Where: {_where(f)}",
        f"What: {WHAT.get(f.kind, f.kind)}",
    ]
    if f.source == "diff":
        lines.append(f"Seen in: {f.differing} of {len(f.samples)} sampled requests")
    if examples:
        lines += ["Examples:", *examples]
    for k in ("observed", "declared"):
        if k in f.type_info:
            lines.append(f"{k.capitalize()} type: {f.type_info[k]}")
    return "\n".join(lines)


def apply(f: Finding, a: Answer, th: Thresholds) -> None:
    f.p = a.p_winner
    f.probabilities = a.probabilities
    if a.meta.get("error"):
        f.label, f.status = "unsure", "unsure"
        f.reason = f"LLM error, needs a human: {a.meta['error']}"
        return
    confident = lambda t: (t.auto_accept is None or a.p_winner >= t.auto_accept) \
        and not a.censored and not a.off_list  # noqa: E731
    if a.value == "regression" and confident(th.triage_regression):
        f.label, f.status = "regression", "shown"
    elif a.value == "intended" and th.triage_intended.auto_accept is not None and confident(th.triage_intended):
        f.label, f.status = "intended", "accepted"
    else:
        # Symmetric bar: a label below its confidence bar goes to a human. Unsure is shown, never dismissed.
        f.label, f.status = "unsure", "unsure"
        if a.value in ("intended", "regression"):
            f.type_info["leans"] = a.value


def triage(findings: list[Finding], intent: str, ev: Backend, th: Thresholds,
           tel: Telemetry | None = None, workers: int = 8) -> list[Finding]:
    def one(f: Finding) -> tuple[Finding, Answer, Answer | None]:
        q = Choice(id=question_id(f), instructions=INSTRUCTIONS, criteria=CRITERIA)
        st = state_for(f, intent)
        a = ev.evaluate(st, [q])[q.id]
        apply(f, a, th)
        r = None
        if f.status in ("shown", "unsure") and not a.meta.get("error"):
            r = ev.evaluate(st, [q], reasons=True)[q.id]
            f.reason = r.reason
        return f, a, r

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(one, findings))
    for _, a, r in results:
        tally(tel, [a])
        if r is not None:
            tally(tel, [r])
            if tel is not None and r.reason:
                tel.reasons += 1
    return findings
