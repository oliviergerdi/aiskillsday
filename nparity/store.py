"""Run <-> runs/<id>.yaml."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from nparity.models import Run

DEFAULT_DIR = Path("runs")


def save(run: Run, dir: str | Path = DEFAULT_DIR) -> Path:
    d = Path(dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{run.id}.yaml"
    data = run.model_dump(mode="json")
    tmp = NamedTemporaryFile(mode="w", encoding="utf-8", dir=d, delete=False)
    pending = Path(tmp.name)
    try:
        with tmp:
            yaml.safe_dump(data, tmp, sort_keys=False, allow_unicode=True)
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)
    return path


def load(run_id: str, dir: str | Path = DEFAULT_DIR) -> Run:
    path = Path(dir) / f"{run_id}.yaml"
    if not path.is_file():
        raise FileNotFoundError(path)
    return Run.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def delete(run_id: str, dir: str | Path = DEFAULT_DIR) -> None:
    if not run_id or run_id in {".", ".."} or any(char in run_id for char in "/\\\0"):
        raise ValueError("Invalid run ID.")
    (Path(dir) / f"{run_id}.yaml").unlink(missing_ok=True)


def list_runs(dir: str | Path = DEFAULT_DIR) -> list[Run]:
    d = Path(dir)
    if not d.is_dir():
        return []
    runs = []
    for path in d.glob("*.yaml"):
        try:
            runs.append(Run.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))))
        except FileNotFoundError:
            continue
    return sorted(runs, key=lambda r: r.started_at, reverse=True)
