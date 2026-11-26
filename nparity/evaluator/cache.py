"""Cached decorator: one YAML file per question under cache/."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from nparity.evaluator.base import Answer, Backend, Choice


class Cached:
    def __init__(self, inner: Backend, dir: str | Path = "cache"):
        self.inner = inner
        self.dir = Path(dir)
        self.id = inner.id
        self.max_options = inner.max_options

    def key(self, state: str | dict[str, Any], q: Choice, reasons: bool) -> str:
        payload = {
            "backend": self.inner.id,
            "template": getattr(self.inner, "template_version", None),
            "state": state,
            "question": q.model_dump(),
            "reasons": reasons,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:24]

    def evaluate(self, state: str | dict[str, Any], questions: list[Choice],
                 reasons: bool = False) -> dict[str, Answer]:
        self.dir.mkdir(parents=True, exist_ok=True)
        out: dict[str, Answer] = {}
        misses: list[Choice] = []
        keys: dict[str, str] = {}
        for q in questions:
            k = keys[q.id] = self.key(state, q, reasons)
            path = self.dir / f"{k}.yaml"
            if path.is_file():
                a = Answer.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
                a.meta = {**a.meta, "cached": True, "cost_usd": 0.0}
                out[q.id] = a
            else:
                misses.append(q)
        if misses:
            fresh = self.inner.evaluate(state, misses, reasons=reasons)
            for q in misses:
                a = fresh[q.id]
                (self.dir / f"{keys[q.id]}.yaml").write_text(
                    yaml.safe_dump(a.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
                out[q.id] = a
        return out
