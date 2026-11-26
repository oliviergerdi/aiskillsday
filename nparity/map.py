"""Old -> new mapping: rules first, the LLM only for what the rules can't settle (design section 2)."""

from __future__ import annotations

import re
from typing import Any

from nparity.config import Threshold, Thresholds
from nparity.evaluator.base import Answer, Backend, Choice, TooManyOptions, tally
from nparity.models import EndpointMap, FieldMap, MapStatus, Telemetry
from nparity.openapi import Endpoint

NONE = "none"


def status_for(p: float | None, censored: bool, t: Threshold) -> MapStatus:
    if p is None:
        return "unmapped"
    if t.auto_accept is not None and p >= t.auto_accept and not censored:
        return "accepted"
    if censored or (t.needs_review is not None and p >= t.needs_review):
        return "review"
    return "unmapped"


def stems(path: str) -> set[str]:
    """Static path segments, lowercased and naively singularised: /customers/{id} -> {"customer"}."""
    out = set()
    for seg in path.strip("/").split("/"):
        if not seg or seg.startswith("{"):
            continue
        seg = re.sub(r"[^a-z0-9]", "", seg.lower())
        out.add(seg[:-1] if seg.endswith("s") and len(seg) > 3 else seg)
    return out


def props(schema: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return dict((schema or {}).get("properties", {}))


def type_name(schema: dict[str, Any]) -> str:
    if "anyOf" in schema:
        return " | ".join(type_name(s) for s in schema["anyOf"])
    t = schema.get("type", "object")
    if t == "array":
        return f"array of {type_name(schema.get('items', {}))}"
    return str(t)


def describe(ep: Endpoint) -> str:
    fields = ", ".join(props(ep.response_schema)) or "no JSON body"
    return f"{ep.key} returns {{ {fields} }}"


def _top3(a: Answer) -> list[tuple[str, float]]:
    return sorted(a.probabilities.items(), key=lambda kv: kv[1], reverse=True)[:3]


def _ask(ev: Backend, state: dict[str, Any], q: Choice, tel: Telemetry | None) -> Answer:
    if len(q.criteria) > ev.max_options:
        raise TooManyOptions(f"{q.id}: {len(q.criteria)} options > {ev.max_options}")  # Task 12: tournament
    a = ev.evaluate(state, [q])[q.id]
    tally(tel, [a])
    return a


def _dedupe(cands: list[Endpoint]) -> list[Endpoint]:
    seen: set[str] = set()
    out = []
    for c in cands:
        d = describe(c).split(" ", 2)[-1] + str(len(c.path_params)) + c.method
        if d in seen:
            continue
        seen.add(d)
        out.append(c)
    return out


def map_endpoints(old: list[Endpoint], new: list[Endpoint], ev: Backend, th: Thresholds,
                  tel: Telemetry | None = None) -> list[EndpointMap]:
    out: list[EndpointMap] = []
    for o in old:
        same = [n for n in new if n.method == o.method]
        filtered = [n for n in same
                    if stems(o.path) <= stems(n.path) and len(n.path_params) == len(o.path_params)]
        if len(filtered) == 1:
            out.append(EndpointMap(old=o.key, new=filtered[0].key, source="rule", status="accepted"))
            if tel:
                tel.rule_decisions += 1
            continue
        cands = _dedupe(filtered or same)
        if not cands:
            out.append(EndpointMap(old=o.key, new=None, source="rule", status="unmapped"))
            if tel:
                tel.rule_decisions += 1
            continue
        criteria = {c.key: describe(c) for c in cands}
        criteria[NONE] = "None of these: the old endpoint has no counterpart"
        q = Choice(
            id=f"map:endpoint:{o.key}",
            instructions=(f"Old endpoint: {describe(o)}. A rewrite may rename paths, resources and fields. "
                          "Which new endpoint is the best match for it?"),
            criteria=criteria,
        )
        state = {"old_endpoint": o.key, "old_fields": list(props(o.response_schema))}
        a = _ask(ev, state, q, tel)
        new_key = None if a.value == NONE else a.value
        status = "unmapped" if new_key is None else status_for(a.p_winner, a.censored, th.mapping)
        out.append(EndpointMap(old=o.key, new=new_key, source="llm", p=a.p_winner, status=status,
                               top3=_top3(a)))
    return out


def map_fields(pairs: list[tuple[Endpoint, Endpoint]], ev: Backend, th: Thresholds,
               tel: Telemetry | None = None) -> list[FieldMap]:
    """Top-level response fields per mapped endpoint pair."""
    out: list[FieldMap] = []
    for o, n in pairs:
        op, np_ = props(o.response_schema), props(n.response_schema)
        for name in op:
            if name in np_:
                out.append(FieldMap(endpoint=o.key, old=name, new=name, source="rule", status="accepted"))
                if tel:
                    tel.rule_decisions += 1
        left_old = [f for f in op if f not in np_]
        left_new = [f for f in np_ if f not in op]
        for name in left_old:
            if not left_new:
                out.append(FieldMap(endpoint=o.key, old=name, new=None, source="rule", status="accepted"))
                if tel:
                    tel.rule_decisions += 1
                continue
            criteria = {f: f"`{f}` ({type_name(np_[f])})" for f in left_new}
            criteria[NONE] = "None: the value is no longer returned (field dropped)"
            q = Choice(
                id=f"map:field:{o.key}:{name}",
                instructions=(f"Old {o.key} returned field `{name}` ({type_name(op[name])}). "
                              f"In the new {n.key}, which field is the best match for it?"),
                criteria=criteria,
            )
            state = {"old_endpoint": o.key, "new_endpoint": n.key,
                     "old_fields": list(op), "new_fields": list(np_)}
            a = _ask(ev, state, q, tel)
            new_name = None if a.value == NONE else a.value
            out.append(FieldMap(endpoint=o.key, old=name, new=new_name, source="llm", p=a.p_winner,
                                status=status_for(a.p_winner, a.censored, th.mapping)))
    return out
