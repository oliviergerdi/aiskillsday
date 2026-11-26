"""Turn a saved Run into what the templates print. Display only: no analysis happens here."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from nparity.config import Thresholds
from nparity.diff import observed_type
from nparity.findings import renames_for
from nparity.jsonpath import MISSING, child, locate, value_at
from nparity.lists import keys_text, membership
from nparity.models import Finding, Run, Sample
from nparity.replay import fill

KIND_TEXT = {
    "changed": "value changed", "missing_in_new": "missing in new", "added_in_new": "added in new",
    "status_changed": "status changed", "list_length_changed": "list length changed",
    "items_removed": "items only in old", "items_added": "items only in new",
    "type_changed": "type changed", "declared_type_changed": "declared type changed",
    "moved": "moved · from mapping", "renamed": "renamed · from mapping", "dropped": "dropped · from mapping",
}
COLOR = {"regression": "var(--reg)", "unsure": "var(--uns)", "intended": "var(--int)"}
BADGE = {"regression": "b-reg", "unsure": "b-uns", "intended": "b-int"}


@dataclass
class Line:
    text: str
    hl: bool = False
    note: str = ""


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
    run_id: str = ""
    state: str | None = None          # review state (PRD 0001): needs_review | intended_model | accepted | rejected
    entry: Any = None                 # ledger Entry when a human decided
    baseline_status: str | None = None   # new | unchanged, when compared with a baseline
    conf_text: str = ""


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


def _sample_paths(run: Run, f: Finding) -> tuple[str | None, str | None]:
    if not f.path.startswith(("$.", "$[")):
        return None, None
    old_path = new_path = f.path
    field = re.match(r"^\$\.([^.\[]+)(.*)$", f.path)
    if field:
        root_key, rest = field.groups()
        renames = renames_for(f.endpoint, run.fields)
        if f.source == "diff":
            # Diffs use the new field name after normalising the old response.
            old_key = next((old for old, new in renames.items() if new == root_key), root_key)
            old_path = child("$", old_key) + rest
        elif f.kind == "renamed" or f.source == "types":
            new_key = f.type_info.get("new_field") or renames.get(root_key) or root_key
            new_path = child("$", new_key) + rest
    return (
        None if f.kind == "added_in_new" else old_path,
        None if f.kind in ("missing_in_new", "dropped") else new_path,
    )


Position = tuple[str | int, ...]


def _array_matches(body: Any, path: str) -> dict[Position, Any]:
    head, wildcard, tail = path.partition("[*]")
    target = locate(body, head)
    if target is None:
        return {}
    value, keys = target
    if not wildcard:
        return {tuple(keys): value}
    if not isinstance(value, list):
        return {}
    return {(*keys, index, *suffix): item for index, element in enumerate(value)
            for suffix, item in _array_matches(element, tail).items()}


def _array_highlights(f: Finding, s: Sample) -> tuple[dict[Position, str], dict[Position, str]]:
    before = _array_matches(s.old.body, f.path)
    first_before = next(iter(before), None)
    before_example = {first_before: "Before example"} if first_before is not None else {}
    if f.kind == "missing_in_new":
        parent, _, name = f.path.rpartition(".")
        missing = {position: f"Missing field {json.dumps(name, ensure_ascii=False)}"
                   for position, record in _array_matches(s.new.body, parent).items()
                   if isinstance(record, dict) and name not in record}
        return before_example, missing
    after = _array_matches(s.new.body, f.path)
    if f.kind == "added_in_new":
        return {}, dict.fromkeys(after, "")
    if f.kind == "type_changed":
        old_types = {observed_type(value) for value in before.values()}
        new_types = {observed_type(value) for value in after.values()}
        old_changes = {position: "" for position, value in before.items() if observed_type(value) not in new_types}
        new_changes = {position: "" for position, value in after.items() if observed_type(value) not in old_types}
        return old_changes or before_example, new_changes
    return {}, {}


def _lines(body: Any, path: str | None, *, highlights: dict[Position, str] | None = None) -> list[Line]:
    if body is None:
        return [Line("(no body)")]
    if isinstance(body, str):
        return [Line(line) for line in body.splitlines()]

    if highlights is None:
        target = locate(body, path) if path is not None else None
        highlights = {tuple(target[1]): ""} if target is not None else {}
    text = json.dumps(body, indent=2, ensure_ascii=False)
    lines = [Line(line) for line in text.split("\n")]

    def mark(value: Any, position: Position, index: int) -> int:
        if position in highlights:
            lines[index].hl = True
            lines[index].note = highlights[position]
        if isinstance(value, (list, dict)) and value:
            items = value.items() if isinstance(value, dict) else enumerate(value)
            index += 1
            for key, child_value in items:
                index = mark(child_value, (*position, key), index)
        return index + 1

    if highlights:
        mark(body, (), 0)
    return lines


def _kind_text(f: Finding, s: Sample | None) -> str:
    text = KIND_TEXT.get(f.kind, f.kind)
    if s is not None and f.kind == "status_changed":
        text = f"status {s.old.status} → {s.new.status}"
    elif s is not None and f.kind in ("items_removed", "items_added"):
        m = membership(value_at(s.old.body, f.path), value_at(s.new.body, f.path))
        if m:
            k, removed, added = m
            text += ": " + keys_text(k, removed if f.kind == "items_removed" else added, cap=5)
    elif s is not None and f.kind == "list_length_changed":
        a, b = value_at(s.old.body, f.path), value_at(s.new.body, f.path)
        if isinstance(a, list) and isinstance(b, list):
            text = f"list length {len(a)} → {len(b)}"
    if f.source == "diff":
        text += f" · {f.differing} of {len(f.samples)} sample{'s' if len(f.samples) != 1 else ''}"
    if "declared" in f.type_info and f.kind != "declared_type_changed":
        text += " · declared type changed"
    return text


def _pct(p: float) -> str:
    return f"{math.floor(round(p * 1000, 6)) / 10:.1f}".rstrip("0").rstrip(".") + "%"  # floor: never show 100% for 0.9996


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
        threshold_text=("always shown" if thr is None else
                        f"{_pct(thr)} needed to confirm as a regression" if bar is th.triage_regression
                        else f"{_pct(thr)} needed to accept as intended"),
        distribution=dist, conf_text=_pct(f.p) if f.p is not None else "—",
    )
    if s is not None:
        old_path, new_path = _sample_paths(run, f)
        v.sample_label = (f"Sample {idx + 1} of {len(f.samples)} · "
                          f"{request_line(s, 'old')} → {request_line(s, 'new')}")
        v.old_head = str(s.old.status) if s.old.status is not None else (s.old.error or "error")
        v.new_head = str(s.new.status) if s.new.status is not None else (s.new.error or "error")
        old_highlights, new_highlights = (_array_highlights(f, s) if "[*]" in f.path else (None, None))
        v.old_lines = _lines(s.old.body, old_path, highlights=old_highlights)
        v.new_lines = _lines(s.new.body, new_path, highlights=new_highlights)
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


def run_name(run_id: str) -> str:
    """'2026-11-26T124642-petstore-4676e543c67a' -> 'petstore'; other ids are shown as-is."""
    m = re.fullmatch(r"\d{4}-\d\d-\d\dT\d{6}-(.+?)(?:-[0-9a-f]{12})?", run_id)
    return m.group(1) if m else run_id


def backend_label(backend: str) -> str:
    # ponytail: only "flash" gets a special short name; anything else is just capitalised
    return "Flash" if "flash" in backend.lower() else backend.capitalize()


def declared_types(run: Run) -> dict[tuple[str, str], str]:
    return {(f.endpoint, f.path): f.type_info["declared"] for f in run.findings if "declared" in f.type_info}


def value_text(v: Any) -> str:
    return "absent" if v is MISSING else json.dumps(v, ensure_ascii=False)


# ---- PRD 0001: review sections (formatting only; state comes from nparity.review) ----

SECTION_ORDER = ("rejected", "regression", "unsure", "intended", "accepted")


def review_view(run: Run, f: Finding, th: Thresholds, states: dict, comparison=None) -> FindingView:
    v = finding_view(run, f, th)
    v.run_id = run.id
    if f.status != "error":
        v.state, v.entry = states.get(f.id, (None, None))
    if comparison is not None:
        v.baseline_status = comparison.status.get(f.id)
    return v


def build_sections(run: Run, states: dict, th: Thresholds, comparison=None) -> dict[str, list[FindingView]]:
    """rejected | regression (to review) | unsure (to review) | intended (model) | accepted (reviewer)."""
    out: dict[str, list[FindingView]] = {k: [] for k in SECTION_ORDER}
    for f in run.findings:
        state = states.get(f.id, ("needs_review", None))[0]
        if state == "rejected":
            key = "rejected"
        elif state == "accepted":
            key = "accepted"
        elif state == "intended_model":
            key = "intended"
        else:
            key = "regression" if f.status == "shown" else "unsure"
        out[key].append(review_view(run, f, th, states, comparison))
    return out


def review_counts(sections: dict[str, list[FindingView]], run: Run) -> dict[str, int]:
    return {"rejected": len(sections["rejected"]), "regression": len(sections["regression"]),
            "unsure": len(sections["unsure"]), "intended": len(sections["intended"]),
            "accepted": len(sections["accepted"]), "noise": len(run.noise), "error": len(run.errors)}
