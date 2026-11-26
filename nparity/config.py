"""YAML config and fixture loaders."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


def load_yaml(path: str | Path) -> Any:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


class Seeds(BaseModel):
    params: dict[str, list[Any]] = Field(default_factory=dict)
    bodies: dict[str, list[Any]] = Field(default_factory=dict)
    methods: list[str] | None = None     # e.g. [GET] for public servers: never mutate data you don't own


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


class NoiseRules(BaseModel):
    mask: list[MaskRule] = Field(default_factory=list)
    unordered: list[UnorderedRule] = Field(default_factory=list)


def load_noise(path: str | Path = "config/noise.yaml") -> NoiseRules:
    return NoiseRules.model_validate(load_yaml(path) or {})
