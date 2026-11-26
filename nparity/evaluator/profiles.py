"""Profile = one model on one provider. Data, not code (evaluator spec section 3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from nparity.config import load_yaml


class Provider(BaseModel):
    base_url: str
    path: str = "/chat/completions"
    api_key_env: str
    model: str


class RequestCfg(BaseModel):
    temperature: float = 0
    max_tokens: int = 1
    logprobs: bool = True
    top_logprobs: int = 5
    extra: dict[str, Any] = Field(default_factory=dict)


class Limits(BaseModel):
    top_logprobs_max: int = 5
    calibrated_options: int = 5
    max_options: int = 30
    concurrency: int = 8
    timeout_s: float = 30


class ReasonCfg(BaseModel):
    max_tokens: int = 60


class Price(BaseModel):
    input_per_mtok_usd: float | None = None
    cached_input_per_mtok_usd: float | None = None
    output_per_mtok_usd: float | None = None
    per_call_usd_estimate: float = 0.0

    def cost(self, prompt: int, cached: int, completion: int) -> float:
        if self.input_per_mtok_usd is None or self.output_per_mtok_usd is None:
            return self.per_call_usd_estimate
        cached_rate = self.cached_input_per_mtok_usd if self.cached_input_per_mtok_usd is not None \
            else self.input_per_mtok_usd
        return ((prompt - cached) * self.input_per_mtok_usd + cached * cached_rate
                + completion * self.output_per_mtok_usd) / 1e6


class Profile(BaseModel):
    id: str
    version: int
    backend: str
    provider: Provider
    request: RequestCfg = Field(default_factory=RequestCfg)
    limits: Limits = Field(default_factory=Limits)
    reason: ReasonCfg = Field(default_factory=ReasonCfg)
    price: Price = Field(default_factory=Price)

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"


def load_profile(path: str | Path) -> Profile:
    return Profile.model_validate(load_yaml(path))
