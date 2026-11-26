"""Saved run configurations: comparisons/<name>.yaml, one RunInput each (PRD 0001)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from app.web.run_sources import SourceInput

DEFAULT_DIR = Path("comparisons")


class RunInput(BaseModel):
    before: SourceInput
    after: SourceInput
    seeds: str = Field(default="", max_length=4096)
    samples: str = Field(default="", max_length=4096)
    discover_from: list[str] = Field(default_factory=list, max_length=20)
    contract_only: bool = False
    flow_mapping: bool = False
    intent: str = Field(default="", max_length=4096)
    intent_text: str = Field(default="", max_length=20000)   # pasted note wins over the `intent` file
    backend: Literal["fake", "flash"] = "fake"
    name: str = Field(default="comparison", max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    score: bool = False
    # per start, never saved:
    save_config: bool = False
    baseline: str = Field(default="auto", max_length=200)   # "auto", "" for none, or a run id


SAVED_FIELDS = {"before", "after", "seeds", "samples", "discover_from", "contract_only", "flow_mapping",
                "intent", "backend", "name", "score"}


NAME = re.compile(r"^[a-zA-Z0-9_-]{1,50}$")


def config_path(name: str, dir: Path = DEFAULT_DIR) -> Path:
    if not NAME.match(name):
        raise ValueError(f"Invalid configuration name {name!r}")
    return Path(dir) / f"{name}.yaml"


def save_config(inputs: RunInput, dir: Path = DEFAULT_DIR) -> Path:
    Path(dir).mkdir(parents=True, exist_ok=True)
    path = config_path(inputs.name, dir)
    data = inputs.model_dump(mode="json", include=SAVED_FIELDS)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def load_config(name: str, dir: Path = DEFAULT_DIR) -> RunInput:
    path = config_path(name, dir)
    if not path.is_file():
        raise FileNotFoundError(path)
    return RunInput.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def list_configs(dir: Path = DEFAULT_DIR) -> list[RunInput]:
    d = Path(dir)
    if not d.is_dir():
        return []
    return sorted((RunInput.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))
                   for p in d.glob("*.yaml")), key=lambda c: c.name)
