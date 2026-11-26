"""All pydantic types shared by the pipeline, the store and the front ends."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

MapSource = Literal["rule", "llm", "llm_tournament"]
MapStatus = Literal["accepted", "review", "unmapped"]

FindingKind = Literal[
    "changed",
    "missing_in_new",
    "added_in_new",
    "status_changed",
    "list_length_changed",
    "type_changed",
    "declared_type_changed",
    "moved",
    "renamed",
    "dropped",
]
FindingSource = Literal["diff", "types", "mapping"]
Label = Literal["intended", "regression", "unsure"]
FindingStatus = Literal["accepted", "shown", "unsure", "error"]


class Request(BaseModel):
    """One HTTP request. `path` is the template, e.g. "/orders/{id}"; values live in `params`."""

    method: str
    path: str
    params: dict[str, Any] = Field(default_factory=dict)
    body: Any = None

    @property
    def endpoint(self) -> str:
        return f"{self.method} {self.path}"


class HttpResult(BaseModel):
    status: int | None
    body: Any = None
    error: str | None = None


class Sample(BaseModel):
    old_request: Request
    new_request: Request | None
    old: HttpResult
    new: HttpResult


class EndpointMap(BaseModel):
    old: str
    new: str | None
    source: MapSource
    p: float | None = None
    status: MapStatus
    top3: list[tuple[str, float]] = Field(default_factory=list)
    error: str | None = None          # the LLM call failed; unmapped because of an error, not a decision


class FieldMap(BaseModel):
    endpoint: str
    old: str
    new: str | None
    source: Literal["rule", "llm"]
    p: float | None = None
    status: MapStatus
    error: str | None = None


class Finding(BaseModel):
    id: str
    endpoint: str
    new_endpoint: str | None = None
    path: str
    kind: FindingKind
    source: FindingSource
    samples: list[Sample] = Field(default_factory=list)
    differing: int = 0
    differs_in: list[int] = Field(default_factory=list)    # indexes into samples
    type_info: dict[str, str] = Field(default_factory=dict)
    label: Label | None = None
    p: float | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    status: FindingStatus | None = None
    reason: str | None = None


class Noise(BaseModel):
    endpoint: str
    path: str
    rule: str


class Score(BaseModel):
    correct: int
    total: int
    unsure: int
    false_regressions: int
    details: list[dict[str, Any]] = Field(default_factory=list)


class Telemetry(BaseModel):
    llm_calls: int = 0
    rule_decisions: int = 0
    reasons: int = 0
    retries: int = 0
    seconds: float = 0.0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


class Run(BaseModel):
    id: str
    started_at: datetime
    config: dict[str, Any] = Field(default_factory=dict)
    endpoints: list[EndpointMap] = Field(default_factory=list)
    fields: list[FieldMap] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    noise: list[Noise] = Field(default_factory=list)
    errors: list[Finding] = Field(default_factory=list)
    score: Score | None = None
    telemetry: Telemetry = Field(default_factory=Telemetry)


class AnswerKey(BaseModel):
    mapping: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
