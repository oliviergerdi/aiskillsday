"""Wire the steps: generate -> map -> replay -> normalise/diff/types -> findings -> triage -> score."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from nparity.config import load_noise, load_seeds, load_thresholds, load_yaml
from nparity.evaluator.base import Backend, build
from nparity.findings import build_findings
from nparity.generate import generate
from nparity.map import map_endpoints, map_fields
from nparity.models import AnswerKey, Run, Telemetry
from nparity.openapi import endpoints, load_spec
from nparity.replay import replay
from nparity.retry import RetryPolicy
from nparity.score import score
from nparity.triage import triage


@dataclass
class RunConfig:
    old: str
    new: str
    intent: Path = Path("fixtures/intent.md")
    seeds: Path = Path("fixtures/seeds.yaml")
    answer_key: Path | None = Path("fixtures/answer_key.yaml")
    noise: Path = Path("config/noise.yaml")
    thresholds: Path = Path("config/thresholds.yaml")
    backend: str = "fake"
    name: str = "toy"
    workers: int = 8
    retry: RetryPolicy = field(default_factory=RetryPolicy)


def run(cfg: RunConfig, client: httpx.Client, ev: Backend | None = None) -> Run:
    started = datetime.now(UTC)
    t0 = time.perf_counter()
    tel = Telemetry()

    if ev is None:
        ev = build(cfg.backend, answer_key=cfg.answer_key or "fixtures/answer_key.yaml")
    th = load_thresholds(cfg.thresholds, ev.id)

    v1 = endpoints(load_spec(client, cfg.old))
    v2 = endpoints(load_spec(client, cfg.new))

    emap = map_endpoints(v1, v2, ev, th, tel)
    new_by_key = {e.key: e for e in v2}
    pairs = [(o, new_by_key[m.new]) for o, m in zip(v1, emap) if m.new and m.status != "unmapped"]
    fmap = map_fields(pairs, ev, th, tel)

    reqs = generate(v1, load_seeds(cfg.seeds))
    samples, retries = replay(reqs, {m.old: m for m in emap}, client, cfg.old, cfg.new, cfg.retry, cfg.workers)
    tel.retries += retries

    findings, noise, errors = build_findings(emap, fmap, samples, load_noise(cfg.noise), v1, v2)
    intent = Path(cfg.intent).read_text(encoding="utf-8")
    triage(findings, intent, ev, th, tel, workers=cfg.workers)

    result = Run(
        id=f"{started.astimezone():%Y-%m-%dT%H%M%S}-{cfg.name}",   # local time, readable
        started_at=started,
        config={"old": cfg.old, "new": cfg.new, "intent": str(cfg.intent), "seeds": str(cfg.seeds),
                "backend": ev.id, "requests": len(reqs), "endpoints": len(v1)},
        endpoints=emap, fields=fmap, findings=findings, noise=noise, errors=errors, telemetry=tel,
    )
    if cfg.answer_key:
        result.score = score(result, AnswerKey.model_validate(load_yaml(cfg.answer_key)))
    tel.seconds = round(time.perf_counter() - t0, 2)
    return result
