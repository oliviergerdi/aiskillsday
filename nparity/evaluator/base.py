"""Jev-shaped evaluator contract (evaluator spec section 2, trimmed to `choice`)."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class Choice(BaseModel):
    """Unordered options. Keys are what the caller gets back; descriptions are what the model reads."""

    id: str
    instructions: str
    criteria: dict[str, str]


class Answer(BaseModel):
    value: str                                  # winning key
    probabilities: dict[str, float]             # display distribution over keys, sums to 1
    p_winner: float                             # winner's raw probability (thresholds use this)
    confidence: float                           # 1 - normalised entropy of `probabilities`
    unseen_mass: float = 0.0
    censored: bool = False
    off_list: bool = False
    reason: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class Backend(Protocol):
    id: str
    max_options: int

    def evaluate(self, state: str | dict[str, Any], questions: list[Choice],
                 reasons: bool = False) -> dict[str, Answer]: ...


class TooManyOptions(ValueError):
    pass


def confidence(probs: dict[str, float]) -> float:
    n = len(probs)
    if n <= 1:
        return 1.0
    h = -sum(p * math.log(p) for p in probs.values() if p > 0)
    return max(0.0, 1.0 - h / math.log(n))


def one_hot(winner: str, keys: list[str], **kw: Any) -> Answer:
    probs = {k: (1.0 if k == winner else 0.0) for k in keys}
    return Answer(value=winner, probabilities=probs, p_winner=1.0, confidence=1.0, **kw)


def uniform(keys: list[str], **kw: Any) -> Answer:
    p = 1.0 / len(keys)
    return Answer(value=keys[0], probabilities={k: p for k in keys}, p_winner=p,
                  confidence=0.0, off_list=True, **kw)


def build(name: str | None = None, *, answer_key: str | Path = "fixtures/answer_key.yaml",
          cache_dir: str | Path = "cache") -> Backend:
    """NPARITY_LLM=fake|flash, default fake. Real backends are wrapped in the YAML cache; fake is not."""
    from nparity.evaluator.cache import Cached

    name = name or os.environ.get("NPARITY_LLM", "fake")
    if name == "fake":
        from nparity.evaluator.fake import FakeBackend

        return FakeBackend.from_file(answer_key)
    if name == "flash":
        from nparity.evaluator.logprob_chat import LogprobChatBackend  # Task 11

        return Cached(LogprobChatBackend.from_profile("config/profiles/flash.yaml"), cache_dir)
    raise ValueError(f"unknown backend {name!r}")


def tally(tel: Any, answers: "list[Answer] | dict[str, Answer]") -> None:
    """Add LLM answers to a models.Telemetry (duck-typed to avoid an import cycle)."""
    if tel is None:
        return
    for a in (answers.values() if isinstance(answers, dict) else answers):
        tel.llm_calls += 1
        tel.cost_usd += float(a.meta.get("cost_usd") or 0.0)
        tel.prompt_tokens += int(a.meta.get("prompt_tokens") or 0)
        tel.cached_tokens += int(a.meta.get("cached_tokens") or 0)
        tel.completion_tokens += int(a.meta.get("completion_tokens") or 0)
        tel.retries += int(a.meta.get("retries") or 0)
        if a.reason and a.meta.get("reason_call"):
            tel.reasons += 1
