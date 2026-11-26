"""Human review on top of a run: ledger, review state, verdict, baseline comparison (PRD 0001).

Review state is computed at view time and never stored in a run file, so a decision applies to every
run in its scope, including runs made before it.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from nparity.models import Finding, Run

Decision = Literal["accept", "reject"]
ReviewState = Literal["needs_review", "intended_model", "accepted", "rejected"]

_LOCK = threading.Lock()


def finding_key(f: Finding) -> str:
    """Stable across runs (unlike f-003 ids): endpoint pair, path, kind. Exact match only."""
    return f"{f.endpoint} -> {f.new_endpoint or '-'} | {f.path} | {f.kind}"


def scope_of(run: Run) -> str:
    """The configuration a run came from, else its old -> new base URLs."""
    scope = run.config.get("config") or f"{run.config.get('old')} -> {run.config.get('new')}"
    return f"{scope} [separate datasets]" if run.config.get("independent_data") else scope


class Entry(BaseModel):
    scope: str
    key: str
    endpoint: str
    path: str
    kind: str
    decision: Decision
    by: str
    at: datetime
    note: str = ""
    run: str
    model_label: str | None = None
    model_p: float | None = None


class Ledger(BaseModel):
    path: Path
    entries: list[Entry] = Field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "Ledger":
        p = Path(path)
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else None
        return cls(path=p, entries=[Entry.model_validate(e) for e in (raw or {}).get("entries", [])])

    def save(self) -> None:
        data = {"entries": [e.model_dump(mode="json") for e in self.entries]}
        self.path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")

    def get(self, scope: str, key: str) -> Entry | None:
        return next((e for e in self.entries if e.scope == scope and e.key == key), None)

    def in_scope(self, scope: str) -> list[Entry]:
        return [e for e in self.entries if e.scope == scope]

    def record(self, run: Run, f: Finding, decision: Decision, by: str, note: str = "") -> Entry:
        by = by.strip()
        if not by:
            raise ValueError("A decision needs the reviewer's name.")
        if decision not in ("accept", "reject"):
            raise ValueError(f"Unknown decision {decision!r}.")
        entry = Entry(scope=scope_of(run), key=finding_key(f), endpoint=f.endpoint, path=f.path, kind=f.kind,
                      decision=decision, by=by, at=datetime.now().astimezone(), note=note.strip(),
                      run=run.id, model_label=f.label, model_p=f.p)
        with _LOCK:
            self.entries = [e for e in self.entries if not (e.scope == entry.scope and e.key == entry.key)]
            self.entries.append(entry)
            self.save()
        return entry

    def remove(self, scope: str, key: str) -> bool:
        with _LOCK:
            before = len(self.entries)
            self.entries = [e for e in self.entries if not (e.scope == scope and e.key == key)]
            if len(self.entries) == before:
                return False
            self.save()
            return True


def review_states(run: Run, ledger: Ledger) -> dict[str, tuple[ReviewState, Entry | None]]:
    """By finding id. A ledger decision wins over the model; otherwise model-accepted is intended."""
    scope = scope_of(run)
    out: dict[str, tuple[ReviewState, Entry | None]] = {}
    for f in run.findings:
        e = ledger.get(scope, finding_key(f))
        if e is not None:
            out[f.id] = ("accepted" if e.decision == "accept" else "rejected", e)
        elif f.status == "accepted":
            out[f.id] = ("intended_model", None)
        else:
            out[f.id] = ("needs_review", None)
    return out


def _n(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def open_counts(run: Run, ledger: Ledger) -> dict[str, int]:
    states = [s for s, _ in review_states(run, ledger).values()]
    rejected, needs = states.count("rejected"), states.count("needs_review")
    return {"rejected": rejected, "needs_review": needs, "errors": len(run.errors),
            "open": rejected + needs + len(run.errors), "accepted": states.count("accepted"),
            "intended_model": states.count("intended_model")}


def verdict(run: Run, ledger: Ledger) -> tuple[str, str]:
    """(text, css class). Ready only when nothing is open: no rejects, nothing unreviewed, no errors."""
    c = open_counts(run, ledger)
    if c["open"] == 0:
        if run.config.get("limited_comparison"):
            if "contract_only" in run.config and not any(row.compared for row in run.coverage):
                return "No usable response comparisons", "uns"
            return "No open items in the sampled responses", "uns"
        if run.config.get("contract_only"):
            return "Contract checked. Behaviour was not replayed.", "uns"
        if run.coverage and not any(row.compared for row in run.coverage):
            return "No usable behaviour comparisons", "uns"
        if run.config.get("independent_data"):
            return "Response shapes reviewed. Use shared data for cutover sign-off.", "uns"
        return "Ready to cut over", "int"
    text = (f"{_n(c['open'], 'open item')}: {_n(c['rejected'], 'confirmed regression')}, "
            f"{c['needs_review']} need review")
    if c["errors"]:
        text += f", {_n(c['errors'], 'error')}"
    states = review_states(run, ledger)
    worst_reg = c["rejected"] or c["errors"] or any(
        s == "needs_review" and f.label == "regression" for f in run.findings for s, _ in [states[f.id]])
    return text, "reg" if worst_reg else "uns"


def stale(run: Run, ledger: Ledger) -> list[Entry]:
    """Entries in this run's scope that match no finding in it ("no longer seen")."""
    keys = {finding_key(f) for f in run.findings}
    return [e for e in ledger.in_scope(scope_of(run)) if e.key not in keys]


class Comparison(BaseModel):
    baseline_id: str
    baseline_started_at: datetime
    status: dict[str, Literal["new", "unchanged"]]     # by finding id in the run
    resolved: list[Finding] = Field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        values = list(self.status.values())
        return {"new": values.count("new"), "unchanged": values.count("unchanged"), "resolved": len(self.resolved)}


def compare(run: Run, baseline: Run) -> Comparison:
    base_keys = {finding_key(f) for f in baseline.findings}
    run_keys = {finding_key(f) for f in run.findings}
    return Comparison(
        baseline_id=baseline.id, baseline_started_at=baseline.started_at,
        status={f.id: ("unchanged" if finding_key(f) in base_keys else "new") for f in run.findings},
        resolved=[f for f in baseline.findings if finding_key(f) not in run_keys],
    )


def latest_baseline(run_or_scope: Run | str, runs: list[Run], before: datetime | None = None,
                    exclude: str | None = None) -> Run | None:
    """Newest run in the same scope, started before `before`, never `exclude` (the run itself)."""
    if isinstance(run_or_scope, Run):
        scope = scope_of(run_or_scope)
        exclude = exclude or run_or_scope.id
        before = before or run_or_scope.started_at
    else:
        scope = run_or_scope
    candidates = [r for r in runs if scope_of(r) == scope and r.id != exclude
                  and (before is None or r.started_at < before)]
    return max(candidates, key=lambda r: r.started_at, default=None)


class Agreement(BaseModel):
    """How the model's labels compare with human decisions in the run's scope (PRD 0002).

    Agreement, not accuracy: reviewers saw the model's label before deciding.
    """
    decided: int = 0
    agree: int = 0
    false_regressions: int = 0      # human accepted, model said regression
    missed_regressions: int = 0     # human rejected, model said intended: the dangerous one
    model_unsure: int = 0
    undecided: int = 0

    @property
    def text(self) -> str:
        scored = self.decided - self.model_unsure
        return (f"Agreement with reviewers: {self.agree}/{scored} decided · {self.false_regressions} false regressions"
                f" · {self.missed_regressions} missed · {self.model_unsure} model unsure"
                f" · {self.undecided} not yet reviewed")


def agreement(run: Run, ledger: Ledger) -> Agreement:
    a = Agreement()
    scope = scope_of(run)
    for f in run.findings:
        e = ledger.get(scope, finding_key(f))
        if e is None:
            a.undecided += 1
            continue
        a.decided += 1
        if f.label == "unsure" or f.label is None:
            a.model_unsure += 1
        elif (e.decision, f.label) in (("accept", "intended"), ("reject", "regression")):
            a.agree += 1
        elif e.decision == "accept":
            a.false_regressions += 1
        else:
            a.missed_regressions += 1
    return a
