"""FakeBackend: answers from the answer key. Tests and offline demo fallback.

Question id conventions (shared with map.py and triage.py):
  map:endpoint:<old endpoint>              -> answer key mapping {old, new}
  map:field:<old endpoint>:<old field>     -> answer key mapping {endpoint, old_field, new_field}
  triage:<old endpoint>:<path>             -> answer key findings {endpoint, path, expect}
A null mapping target answers "none". Anything not in the key gets a uniform, off-list answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nparity.config import load_yaml
from nparity.evaluator.base import Answer, Choice, one_hot, uniform
from nparity.models import AnswerKey


class FakeBackend:
    id = "fake"
    max_options = 255

    def __init__(self, key: AnswerKey):
        self.key = key

    @classmethod
    def from_file(cls, path: str | Path) -> "FakeBackend":
        return cls(AnswerKey.model_validate(load_yaml(path)))

    def expected(self, qid: str) -> str | None:
        if qid.startswith("map:endpoint:"):
            old = qid.removeprefix("map:endpoint:")
            for m in self.key.mapping:
                if m.get("old") == old:
                    return m.get("new") or "none"
        elif qid.startswith("map:field:"):
            endpoint, _, field = qid.removeprefix("map:field:").rpartition(":")
            for m in self.key.mapping:
                if m.get("endpoint") == endpoint and m.get("old_field") == field:
                    return m.get("new_field") or "none"
        elif qid.startswith("triage:"):
            endpoint, _, path = qid.removeprefix("triage:").partition(":")
            for f in self.key.findings:
                if f["endpoint"] == endpoint and f["path"] == path and f["expect"] != "noise":
                    return f["expect"]
        return None

    def evaluate(self, state: str | dict[str, Any], questions: list[Choice],
                 reasons: bool = False) -> dict[str, Answer]:
        out: dict[str, Answer] = {}
        for q in questions:
            keys = list(q.criteria)
            want = self.expected(q.id)
            meta = {"backend": self.id, "latency_s": 0.0, "cost_usd": 0.0}
            reason = "fake: from answer key" if reasons else None
            if want in q.criteria:
                out[q.id] = one_hot(want, keys, meta=meta, reason=reason)
            else:
                out[q.id] = uniform(keys, meta=meta, reason=reason)
        return out
