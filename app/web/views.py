"""Turn a saved Run into what the templates print. Display only: no analysis happens here."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from nparity.config import Thresholds
from nparity.jsonpath import MISSING, value_at
from nparity.models import Finding, Run, Sample
from nparity.replay import fill

KIND_TEXT = {
    "changed": "value changed", "missing_in_new": "missing in new", "added_in_new": "added in new",
    "status_changed": "status changed", "list_length_changed": "list length changed",
    "type_changed": "type changed", "declared_type_changed": "declared type changed",
    "moved": "moved · from mapping", "renamed": "renamed · from mapping", "dropped": "dropped · from mapping",
}
COLOR = {"regression": "var(--reg)", "unsure": "var(--uns)", "intended": "var(--int)"}
BADGE = {"regression": "b-reg", "unsure": "b-uns", "intended": "b-int"}


@dataclass
class Line:
    text: str
    hl: bool = False


@dataclass
class FindingView:
    f: Finding
    kind_text: str
    p_text: str
    p_pct: float
    color: str
    thr_pct: float | None
    badge: str
    threshold_text: str
    distribution: str
    sample_label: str = ""
    old_head: str = ""
    new_head: str = ""
    old_lines: list[Line] = field(default_factory=list)
    new_lines: list[Line] = field(default_factory=list)
    samples: list[tuple[str, str]] = field(default_factory=list)
    body_html: str = ""


@dataclass
class Group:
    endpoint: str
    new_endpoint: str | None
    items: list
    count: int
    min_p: float | None


def group_findings(views: list) -> list[Group]:
    """Group finding views by (endpoint, new_endpoint); lowest p first, then bigger groups, unknown p last."""
    by_key: dict[tuple, list] = {}
    for v in views:
        by_key.setdefault((v.f.endpoint, v.f.new_endpoint), []).append(v)
    groups = []
    for (ep, new), items in by_key.items():
        ps = [v.f.p for v in items if v.f.p is not None]
        groups.append(Group(ep, new, items, len(items), min(ps) if ps else None))
    return sorted(groups, key=lambda g: (g.min_p is None, g.min_p or 0, -g.count))


def request_line(s: Sample, side: str) -> str:
    req = s.old_request if side == "old" else s.new_request
    if req is None:
        return "—"
    path, query = fill(req)
    qs = "?" + "&".join(f"{k}={v}" for k, v in query.items()) if query else ""
    return f"{req.method} {path}{qs}"


def _leaf(path: str) -> str | None:
    if path in ("status", "endpoint", "request", "$"):
        return None
    return re.sub(r"\[\d+\]", "", path.rsplit(".", 1)[-1])


def _lines(body: Any, key: str | None) -> list[Line]:
    if body is None:
        return [Line("(no body)")]
    text = json.dumps(body, indent=2, ensure_ascii=False) if not isinstance(body, str) else body
    return [Line(t, bool(key) and f'"{key}":' in t) for t in text.splitlines()]


def _kind_text(f: Finding, s: Sample | None) -> str:
    text = KIND_TEXT.get(f.kind, f.kind)
    if s is not None and f.kind == "status_changed":
        text = f"status {s.old.status} → {s.new.status}"
    elif s is not None and f.kind == "list_length_changed":
        a, b = value_at(s.old.body, f.path), value_at(s.new.body, f.path)
        if isinstance(a, list) and isinstance(b, list):
            text = f"list length {len(a)} → {len(b)}"
    if f.source == "diff":
        text += f" · {f.differing} of {len(f.samples)} sample{'s' if len(f.samples) != 1 else ''}"
    if "declared" in f.type_info and f.kind != "declared_type_changed":
        text += " · declared type changed"
    return text


def finding_view(run: Run, f: Finding, th: Thresholds) -> FindingView:
    label = f.label or "unsure"
    leans = f.type_info.get("leans")
    bar = th.triage_regression if (label == "regression" or leans == "regression") else th.triage_intended
    thr = bar.auto_accept
    idx = f.differs_in[0] if f.differs_in else (0 if f.samples else None)
    s = f.samples[idx] if idx is not None and idx < len(f.samples) else None
    dist = " · ".join(f"{k} {v:.2f}" for k, v in sorted(f.probabilities.items(), key=lambda kv: -kv[1]))
    v = FindingView(
        f=f, kind_text=_kind_text(f, s),
        p_text=f"{f.p:.3f}" if f.p is not None else "—",
        p_pct=round((f.p or 0) * 100, 1), color=COLOR.get(label, "var(--noi)"),
        thr_pct=round(thr * 100, 1) if thr is not None else None, badge=BADGE.get(label, "b-noi"),
        threshold_text=(f"{leans or label} needs {thr}" if thr is not None else "always shown"),
        distribution=dist,
    )
    if s is not None:
        old_key = new_key = _leaf(f.path)
        if f.kind == "renamed":
            new_key = next((m.new for m in run.fields if m.endpoint == f.endpoint and m.old == old_key), None)
        elif f.kind == "dropped":
            new_key = None
        v.sample_label = (f"Sample {idx + 1} of {len(f.samples)} · "
                          f"{request_line(s, 'old')} → {request_line(s, 'new')}")
        v.old_head = str(s.old.status) if s.old.status is not None else (s.old.error or "error")
        v.new_head = str(s.new.status) if s.new.status is not None else (s.new.error or "error")
        v.old_lines, v.new_lines = _lines(s.old.body, old_key), _lines(s.new.body, new_key)
    for i, smp in enumerate(f.samples):
        if f.source == "diff":
            state = "differs" if i in f.differs_in else "same"
        else:
            state = f"{smp.old.status} / {smp.new.status}"
        v.samples.append((request_line(smp, "old"), state))
    return v


def counts(run: Run) -> dict[str, int]:
    st = [f.status for f in run.findings]
    return {"regression": st.count("shown"), "unsure": st.count("unsure"), "intended": st.count("accepted"),
            "noise": len(run.noise), "error": len(run.errors)}


def verdict(c: dict[str, int]) -> tuple[str, str]:
    if c["regression"] or c["unsure"]:
        return f"{c['regression']} regressions and {c['unsure']} unsure need review", "reg" if c["regression"] else "uns"
    return "No regressions found", "int"


def declared_types(run: Run) -> dict[tuple[str, str], str]:
    return {(f.endpoint, f.path): f.type_info["declared"] for f in run.findings if "declared" in f.type_info}


def value_text(v: Any) -> str:
    return "absent" if v is MISSING else json.dumps(v, ensure_ascii=False)
