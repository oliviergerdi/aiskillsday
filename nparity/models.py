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
    "items_removed",
    "items_added",
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
    seed_sources: dict[str, str] = Field(default_factory=dict)

    @property
    def endpoint(self) -> str:
        return f"{self.method} {self.path}"


class HttpResult(BaseModel):
    status: int | None
    body: Any = None
    error: str | None = None


class RequestPair(BaseModel):
    old: Request
    new: Request


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


class ContractChange(BaseModel):
    endpoint: str
    new_endpoint: str | None = None
    section: str
    before: Any = None
    after: Any = None


class EndpointCoverage(BaseModel):
    endpoint: str
    seed_sources: list[str] = Field(default_factory=list)
    contract_compared: bool = False
    compared: int = 0
    attempted: int = 0
    reason: str | None = None


FlowRole = Literal["direct", "auth", "configure", "start", "await", "read", "page", "none"]


class FlowCitation(BaseModel):
    reference: str
    quote: str


class FlowStep(BaseModel):
    new_op: str
    role: FlowRole
    p: float = Field(ge=0, le=1)
    status: Literal["suggested", "unsure"]
    source: FlowCitation | None = None
    warning: str | None = None


class FlowMap(BaseModel):
    old_op: str
    steps: list[FlowStep] = Field(default_factory=list)
    status: Literal["needs_review"] = "needs_review"
    ordering_warning: str | None = None


class FlowScores(BaseModel):
    op_recall: float | None
    step_precision: float | None
    order_and_roles: float | None
    unmatched_old: bool
    unmatched_new: bool


class FlowMapping(BaseModel):
    flows: list[FlowMap] = Field(default_factory=list)
    unmatched_old: list[str] = Field(default_factory=list)
    unmatched_new: list[str] = Field(default_factory=list)
    none_count: int = 0
    score: FlowScores | None = None


class FlowKeyStep(BaseModel):
    new_op: str
    role: FlowRole
    alt: str | None = None


class FlowVariant(BaseModel):
    steps: list[FlowKeyStep] = Field(default_factory=list)


class FlowKeyEntry(FlowVariant):
    old_op: str
    variants: list[FlowVariant] = Field(default_factory=list)

    def paths(self) -> list[FlowVariant]:
        return self.variants or [self]


class FlowKeyUnmatched(BaseModel):
    op: str


class FlowKey(BaseModel):
    version: Literal[1] = 1
    confirmed_by: str | None = None
    flows: list[FlowKeyEntry] = Field(default_factory=list)
    unmatched_old: list[str | FlowKeyUnmatched] = Field(default_factory=list)
    unmatched_new: list[str | FlowKeyUnmatched] = Field(default_factory=list)


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
    contract: list[ContractChange] = Field(default_factory=list)
    coverage: list[EndpointCoverage] = Field(default_factory=list)
    flow_mapping: FlowMapping | None = None

    def basic_checks_summary(self) -> str | None:
        if self.config.get("limited_comparison"):
            if not self.coverage and "contract_only" not in self.config:
                return "No API spec: this saved run used sampled responses. This is not a full comparison."
            compared = sum(row.compared > 0 for row in self.coverage)
            return (f"No API spec: basic checks only. {compared} of {len(self.coverage)} endpoints compared. "
                    "This is not a full comparison.")
        return None

    def independent_data_summary(self) -> str | None:
        if self.config.get("independent_data"):
            return ("The intent describes separate datasets. Replay checks status codes and response shapes. "
                    "Use shared test records to verify value-level behaviour.")
        return None


class AnswerKey(BaseModel):
    mapping: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
