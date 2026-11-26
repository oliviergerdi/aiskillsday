"""Group per-sample diffs and mapping decisions into findings (one triage decision each)."""

from __future__ import annotations

from collections import defaultdict

from nparity.config import NoiseRules
from nparity.diff import diff
from nparity.jsonpath import generic
from nparity.models import EndpointMap, FieldMap, Finding, Noise, Sample
from nparity.normalise import normalise
from nparity.openapi import Endpoint
from nparity.types import declared_diffs, observed_types

MAX_SAMPLES = 5


def renames_for(endpoint: str, fmap: list[FieldMap]) -> dict[str, str | None]:
    return {f.old: f.new for f in fmap
            if f.endpoint == endpoint and f.status != "unmapped" and f.new != f.old}


def _fmt(types: set[str]) -> str:
    return " | ".join(sorted(types)) or "absent"


def build_findings(emap: list[EndpointMap], fmap: list[FieldMap], samples: list[Sample], rules: NoiseRules,
                   old_eps: list[Endpoint], new_eps: list[Endpoint]
                   ) -> tuple[list[Finding], list[Noise], list[Finding]]:
    """Returns (findings, noise, errors). Finding ids are stable: sorted by (endpoint, path, kind)."""
    by_old = {m.old: m for m in emap}
    old_by_key = {e.key: e for e in old_eps}
    new_by_key = {e.key: e for e in new_eps}

    per_endpoint: dict[str, list[Sample]] = defaultdict(list)
    for s in samples:
        per_endpoint[s.old_request.endpoint].append(s)

    groups: dict[tuple[str, str, str], Finding] = {}
    noise: dict[tuple[str, str, str], Noise] = {}
    errors: list[Finding] = []

    for endpoint, eps_samples in per_endpoint.items():
        shown = eps_samples[:MAX_SAMPLES]
        new_endpoint = by_old[endpoint].new if endpoint in by_old else None
        renames = renames_for(endpoint, fmap)
        for i, s in enumerate(eps_samples):
            if s.new.error == "unmapped":
                continue
            if s.old.error or s.new.error:
                errors.append(Finding(id="", endpoint=endpoint, new_endpoint=new_endpoint, path="request",
                                      kind="changed", source="diff", samples=[s], differing=1, differs_in=[0],
                                      status="error", reason=s.old.error or s.new.error))
                continue
            o, n, ns = normalise(endpoint, s.old, s.new, rules, renames)
            for x in ns:
                noise.setdefault((x.endpoint, x.path, x.rule), x)
            for d in diff(o, n, rules.list_keys(endpoint)):
                key = (endpoint, d.path, d.kind)
                f = groups.get(key)
                if f is None:
                    f = groups[key] = Finding(id="", endpoint=endpoint, new_endpoint=new_endpoint, path=d.path,
                                              kind=d.kind, source="diff", samples=shown)
                f.differing += 1
                if i < MAX_SAMPLES:
                    f.differs_in.append(i)

        # observed types, for display on value findings
        obs = observed_types([s for s in eps_samples if s.new.error != "unmapped"])
        for (ep, path, _), f in groups.items():
            if ep == endpoint and generic(path) in obs:
                a, b = obs[generic(path)]
                f.type_info["observed"] = f"{_fmt(a)} → {_fmt(b)}"

    findings = list(groups.values())

    # declared types of mapped fields: attach to an existing finding on the same path, else their own finding
    for m in emap:
        if m.new is None or m.status == "unmapped" or m.old not in old_by_key or m.new not in new_by_key:
            continue
        fm = [f for f in fmap if f.endpoint == m.old]
        for d in declared_diffs(old_by_key[m.old].response_schema, new_by_key[m.new].response_schema, fm):
            target = next((f for f in findings if f.endpoint == m.old and f.path == d.path), None)
            if target is None:
                target = Finding(id="", endpoint=m.old, new_endpoint=m.new, path=d.path,
                                 kind="declared_type_changed", source="types",
                                 samples=per_endpoint.get(m.old, [])[:MAX_SAMPLES])
                findings.append(target)
            target.type_info["declared"] = f"{d.old} → {d.new}"

    # mapping decisions are findings too: moved endpoints, renamed and dropped fields
    for m in emap:
        if m.new is not None and m.status != "unmapped" and m.new != m.old:
            findings.append(Finding(id="", endpoint=m.old, new_endpoint=m.new, path="endpoint", kind="moved",
                                    source="mapping", samples=per_endpoint.get(m.old, [])[:MAX_SAMPLES],
                                    type_info={"mapping": f"{m.old} → {m.new} ({m.source})"}))
    for f in fmap:
        if f.status == "unmapped" or f.new == f.old:
            continue
        kind = "dropped" if f.new is None else "renamed"
        findings.append(Finding(id="", endpoint=f.endpoint, new_endpoint=by_old.get(f.endpoint).new
                                if f.endpoint in by_old else None, path=f"$.{f.old}", kind=kind,
                                source="mapping", samples=per_endpoint.get(f.endpoint, [])[:MAX_SAMPLES],
                                type_info={"mapping": f"{f.old} → {f.new or 'dropped'} ({f.source})",
                                           **({"new_field": f.new} if f.new else {})}))

    # mapping calls that failed are errors, not quiet "unmapped" rows
    for m in emap:
        if m.error:
            errors.append(Finding(id="", endpoint=m.old, path="endpoint", kind="moved", source="mapping",
                                  status="error", reason=f"Endpoint mapping failed: {m.error}"))
    for fm in fmap:
        if fm.error:
            errors.append(Finding(id="", endpoint=fm.endpoint, path=f"$.{fm.old}", kind="renamed",
                                  source="mapping", status="error", reason=f"Field mapping failed: {fm.error}"))

    findings.sort(key=lambda f: (f.endpoint, f.path, f.kind))
    for n, f in enumerate(findings, 1):
        f.id = f"f-{n:03d}"
    for n, e in enumerate(errors, 1):
        e.id = f"e-{n:03d}"
    return findings, sorted(noise.values(), key=lambda x: (x.endpoint, x.path)), errors
