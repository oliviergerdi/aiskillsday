"""YAML config and fixture loaders."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


def load_yaml(path: str | Path) -> Any:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


SeedSource = Literal["manual", "example", "default", "enum", "bounds", "discovered", "sample", "guessed"]


class SeedValue(BaseModel):
    value: Any
    source: SeedSource


class OperationSeeds(BaseModel):
    params: dict[str, list[SeedValue]] = Field(default_factory=dict)
    bodies: list[SeedValue] = Field(default_factory=list)


class Seeds(BaseModel):
    params: dict[str, list[Any]] = Field(default_factory=dict)
    bodies: dict[str, list[Any]] = Field(default_factory=dict)
    methods: list[str] | None = None     # e.g. [GET] for public servers: never mutate data you don't own
    operations: dict[str, OperationSeeds] = Field(default_factory=dict)


def load_seeds(path: str | Path) -> Seeds:
    return Seeds.model_validate(load_yaml(path) or {})


class Threshold(BaseModel):
    auto_accept: float | None = None
    needs_review: float | None = None


class Thresholds(BaseModel):
    mapping: Threshold
    triage_intended: Threshold
    triage_regression: Threshold


def load_thresholds(path: str | Path = "config/thresholds.yaml", backend_id: str | None = None) -> Thresholds:
    raw = load_yaml(path) or {}
    merged = dict(raw.get("default", {}))
    if backend_id and backend_id in raw:
        merged.update(raw[backend_id])
    return Thresholds.model_validate(merged)


class MaskRule(BaseModel):
    endpoint: str
    paths: list[str]


class UnorderedRule(BaseModel):
    endpoint: str
    path: str
    key: str | None = None


class ListRule(BaseModel):
    endpoint: str
    path: str                      # generic path of the list, e.g. "$.items" or "$"
    key: str | None = None         # None = compare by position


class NoiseRules(BaseModel):
    mask: list[MaskRule] = Field(default_factory=list)
    unordered: list[UnorderedRule] = Field(default_factory=list)    # legacy alias of `lists` with a key
    lists: list[ListRule] = Field(default_factory=list)
    defaults: dict[str, bool] = Field(default_factory=lambda: {"datetime": True, "date": True, "uuid": True,
                                                               "epoch": True})

    def list_keys(self, endpoint: str) -> dict[str, object]:
        """generic list path -> key name, or lists.NO_KEY to force positional compare."""
        from nparity.lists import NO_KEY

        out: dict[str, object] = {r.path: r.key for r in self.unordered if r.endpoint == endpoint and r.key}
        for r in self.lists:
            if r.endpoint == endpoint:
                out[r.path] = r.key or NO_KEY
        return out

    def default_on(self, kind: str) -> bool:
        return self.defaults.get(kind, True)


def load_noise(path: str | Path = "config/noise.yaml") -> NoiseRules:
    return NoiseRules.model_validate(load_yaml(path) or {})
