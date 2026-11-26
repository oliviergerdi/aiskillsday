"""Run <-> runs/<id>.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from nparity.models import Run

DEFAULT_DIR = Path("runs")


def save(run: Run, dir: str | Path = DEFAULT_DIR) -> Path:
    d = Path(dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{run.id}.yaml"
    data = run.model_dump(mode="json")
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def load(run_id: str, dir: str | Path = DEFAULT_DIR) -> Run:
    path = Path(dir) / f"{run_id}.yaml"
    if not path.is_file():
        raise FileNotFoundError(path)
    return Run.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def list_runs(dir: str | Path = DEFAULT_DIR) -> list[Run]:
    d = Path(dir)
    if not d.is_dir():
        return []
    runs = [Run.model_validate(yaml.safe_load(p.read_text(encoding="utf-8"))) for p in d.glob("*.yaml")]
    return sorted(runs, key=lambda r: r.started_at, reverse=True)
