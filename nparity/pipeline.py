"""Wire the steps: generate -> map -> replay -> normalise/diff/types -> findings -> triage -> score."""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from nparity import contract, coverage, headers, seed_generation, seed_samples
from nparity.config import Seeds, load_noise, load_seeds, load_thresholds, load_yaml
from nparity.evaluator.base import Backend, build
from nparity.evaluator.fake import FakeBackend
from nparity.findings import build_findings
from nparity.generate import allowed_methods, generate
from nparity.map import map_endpoints, map_fields
from nparity.models import AnswerKey, EndpointMap, RequestPair, Run, Telemetry
from nparity.openapi import Endpoint, endpoints, load_spec
from nparity.replay import replay, replay_pairs, to_new
from nparity.retry import RetryPolicy
from nparity.score import score
from nparity.triage import intent_declares_independent_data, triage

STAGES = (
    ("Loading ", "load"),
    ("Reading API endpoints", "read"),
    ("Mapping endpoints and fields", "map"),
    ("Replaying ", "replay"),
    ("Comparing responses and schemas", "compare"),
    ("Triaging ", "triage"),
    ("Saving report", "save"),
)


def stage_for(message: str) -> str | None:
    return next((stage for prefix, stage in STAGES if message.startswith(prefix)), None)


@dataclass
class RunConfig:
    old: str
    new: str
    intent: Path | None = Path("fixtures/intent.md")
    seeds: Path | None = None
    answer_key: Path | None = Path("fixtures/answer_key.yaml")
    noise: Path = Path("config/noise.yaml")
    thresholds: Path = Path("config/thresholds.yaml")
    old_spec: str | None = None        # URL or file; default <old>/openapi.json
    new_spec: str | None = None
    old_headers: list[str] = field(default_factory=list)     # "Name: env:VAR"; values read at run start
    new_headers: list[str] = field(default_factory=list)
    backend: str = "fake"
    name: str = "toy"
    workers: int = 8
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    discover_from: list[str] = field(default_factory=list)
    seed_samples: Path | None = None
    sample_requests: list[RequestPair] | None = None
    contract_only: bool = False
    run_id: str | None = None


def _optional_spec(client, base, location, request_headers):
    candidates = [location] if location else [f"{base.rstrip('/')}/{name}" for name in ("openapi.json", "swagger.json")]
    for candidate in candidates:
        try:
            spec = load_spec(client, base, candidate, request_headers)
        except httpx.HTTPStatusError as error:
            if error.response.status_code not in {401, 403, 404, 405}:
                raise
            continue
        except (ValueError, yaml.YAMLError):
            continue
        if isinstance(spec, dict) and isinstance(spec.get("paths"), dict):
            return spec
    return None


def _toy_seeds(cfg: RunConfig, old_spec: dict, new_spec: dict) -> Path | None:
    old, new = httpx.URL(cfg.old), httpx.URL(cfg.new)
    local = {"localhost", "127.0.0.1", "::1", "testserver"}
    if (old.host in local and new.host in local
            and (old.path.rstrip("/"), new.path.rstrip("/")) == ("/v1", "/v2")
            and old_spec.get("info", {}).get("title") == "Toy shop v1"
            and new_spec.get("info", {}).get("title") == "Toy shop v2"):
        return Path("fixtures/seeds.yaml")
    return None


def _specs(cfg, client, old_headers, new_headers):
    if cfg.sample_requests is not None:
        return None, None
    return (
        _optional_spec(client, cfg.old, cfg.old_spec, old_headers),
        _optional_spec(client, cfg.new, cfg.new_spec, new_headers),
    )


def _request_seeds(cfg, old_spec, new_spec, endpoints, supplied=None):
    path = cfg.seeds
    if supplied is None:
        path = path or _toy_seeds(cfg, old_spec, new_spec)
        supplied = load_seeds(path) if path else Seeds()
    seeds = seed_generation.fill_gaps(supplied, seed_generation.from_spec(endpoints))
    if cfg.seed_samples is not None:
        seed_samples.apply(cfg.seed_samples, endpoints, seeds, cfg.old)
    return path, seeds


def plan(cfg: RunConfig, client: httpx.Client) -> dict:
    """Forecast replay from specs and local seeds without contacting live endpoints or a model."""
    old_h = headers.resolve(cfg.old_headers, "old")
    new_h = headers.resolve(cfg.new_headers, "new")
    old_spec, new_spec = _specs(cfg, client, old_h, new_h)
    basic = old_spec is None or new_spec is None
    rows = []
    if basic:
        for pair in cfg.sample_requests or []:
            rows.append({"endpoint": pair.old.endpoint, "new_endpoint": pair.new.endpoint, "requests": 1,
                         "seed_sources": ["sample"], "reason": None})
    else:
        before, after = endpoints(old_spec), endpoints(new_spec)
        _, seeds = _request_seeds(cfg, old_spec, new_spec, before) if not cfg.contract_only else (None, Seeds())
        evaluator = FakeBackend.from_file(cfg.answer_key) if cfg.backend == "fake" and cfg.answer_key else FakeBackend(AnswerKey())
        mapped = map_endpoints(before, after, evaluator, load_thresholds(cfg.thresholds, evaluator.id))
        requests = defaultdict(list)
        if not cfg.contract_only:
            for request in generate(before, seeds):
                requests[request.endpoint].append(request)
        allowed = allowed_methods(seeds)
        for endpoint, mapping in zip(before, mapped):
            candidates = requests[endpoint.key]
            count = sum(to_new(request, mapping) is not None for request in candidates)
            reason = None
            if cfg.contract_only:
                reason = "contract only"
            elif endpoint.method not in allowed:
                reason = "method not enabled"
            elif not candidates:
                reason = "not seeded"
            elif not count:
                reason = "mapping unresolved without a model or a compatible endpoint"
            rows.append({"endpoint": endpoint.key, "new_endpoint": mapping.new, "requests": count,
                         "seed_sources": sorted({s for req in candidates for s in req.seed_sources.values()}),
                         "reason": reason})
    return {"dry_run": True, "limited_comparison": basic, "endpoints": rows,
            "requests": sum(row["requests"] for row in rows),
            "discovery": {"allowlist": cfg.discover_from, "executed": False}}


def run(
    cfg: RunConfig, client: httpx.Client, ev: Backend | None = None, *,
    specs: tuple[dict, dict] | None = None,
    request_seeds: Seeds | None = None,
    progress: Callable[[str], None] = lambda _: None,
) -> Run:
    started = datetime.now(UTC)
    t0 = time.perf_counter()
    tel = Telemetry()

    old_h = headers.resolve(cfg.old_headers, "old")     # before any request: a missing variable fails fast
    new_h = headers.resolve(cfg.new_headers, "new")
    intent = Path(cfg.intent).read_text(encoding="utf-8") if cfg.intent is not None and not cfg.contract_only else ""
    independent_data = intent_declares_independent_data(intent)

    progress("Reading API endpoints")
    old_spec, new_spec = specs or _specs(cfg, client, old_h, new_h)
    basic = old_spec is None or new_spec is None
    if ev is None:
        ev = (FakeBackend(AnswerKey()) if cfg.contract_only or (cfg.backend == "fake" and (basic or cfg.answer_key is None))
              else build(cfg.backend, answer_key=cfg.answer_key or "fixtures/answer_key.yaml"))
    th = load_thresholds(cfg.thresholds, ev.id)

    if basic:
        sample_requests = cfg.sample_requests or []
        v1 = list({p.old.endpoint: Endpoint(p.old.method, p.old.path) for p in sample_requests}.values())
        v2 = list({p.new.endpoint: Endpoint(p.new.method, p.new.path) for p in sample_requests}.values())
    else:
        v1, v2 = endpoints(old_spec), endpoints(new_spec)
    progress(f"Mapping endpoints and fields ({len(v1)} before, {len(v2)} after)")
    emap = ([EndpointMap(old=old, new=new, source="rule", status="accepted")
             for old, new in {p.old.endpoint: p.new.endpoint for p in sample_requests}.items()]
            if basic else map_endpoints(v1, v2, ev, th, tel))
    new_by_key = {e.key: e for e in v2}
    pairs = [(o, new_by_key[m.new]) for o, m in zip(v1, emap) if m.new and m.status != "unmapped"]
    fmap = [] if basic or cfg.contract_only else map_fields(pairs, ev, th, tel)
    declared = [] if basic else contract.compare(v1, v2, emap)
    seeds_path = cfg.seeds
    seeds = request_seeds if request_seeds is not None else Seeds()
    reqs = []
    if cfg.contract_only:
        samples, retries = [], 0
    elif basic:
        progress(f"Replaying {len(sample_requests)} supplied GET samples")
        explicit = [(p.old.model_copy(update={"seed_sources": {"$request": "sample"}}), p.new) for p in sample_requests]
        reqs = [old for old, _ in explicit]
        samples, retries = replay_pairs(explicit, client, cfg.old, cfg.new, cfg.retry, cfg.workers, old_h, new_h)
    else:
        seeds_path, seeds = _request_seeds(cfg, old_spec, new_spec, v1, request_seeds)
        if cfg.discover_from and not old_h:
            progress("Discovering seeds from allowlisted GET endpoints")
            safe = [ep for ep in v1 if ep.method == "GET" and ep.key in cfg.discover_from and not ep.has_body]
            discovery_seeds = seeds.model_copy(update={"methods": ["GET"]})
            seed_generation.discover(v1, generate(safe, discovery_seeds, cap=1), client, cfg.old, seeds)
        elif cfg.discover_from:
            progress("Discovery skipped because the before API uses custom request headers.")
        reqs = generate(v1, seeds)
        if not reqs:
            progress("No requests generated. Add seeds for required parameters or request bodies.")
        progress(f"Replaying {len(reqs)} requests")
        samples, retries = replay(reqs, {m.old: m for m in emap}, client, cfg.old, cfg.new, cfg.retry, cfg.workers,
                                  old_headers=old_h, new_headers=new_h)
    tel.retries += retries

    progress("Comparing responses and schemas")
    findings, noise, errors = [], [], []
    if not cfg.contract_only:
        findings, noise, errors = build_findings([] if basic else emap, fmap, samples, load_noise(cfg.noise), v1, v2,
                                                  shape_only=basic, include_declared=False, independent_data=independent_data)
        if independent_data:
            progress(f"Triaging {len(findings)} findings for human review. The intent describes separate datasets.")
            for finding in findings:
                finding.label = finding.status = "unsure"
                finding.reason = "The recorded status or shape differs. Check the same records before judging regression risk."
        else:
            progress(f"Triaging {len(findings)} findings")
            triage(findings, intent, ev, th, tel, workers=cfg.workers)
    matched = {m.new for m in emap if m.new is not None and m.status == "accepted"}

    result = Run(
        id=cfg.run_id or f"{started.astimezone():%Y-%m-%dT%H%M%S}-{cfg.name}",
        started_at=started,
        config={"old": cfg.old, "new": cfg.new, "intent": str(cfg.intent) if cfg.intent is not None else None,
                "seeds": str(seeds_path) if seeds_path else None, "limited_comparison": basic,
                "contract_only": cfg.contract_only, "independent_data": independent_data,
                "backend": ev.id, "requests": len(reqs), "endpoints": len(v1),
                "old_headers": headers.names(cfg.old_headers), "new_headers": headers.names(cfg.new_headers)},
        endpoints=emap, fields=fmap, findings=findings, noise=noise, errors=errors, telemetry=tel,
        contract=declared,
        coverage=coverage.report(v1, v2, samples, allowed_methods(seeds), contract_available=not basic,
                                 matched=matched, contract_only=cfg.contract_only),
    )
    if cfg.answer_key and not basic and not cfg.contract_only and not independent_data:
        result.score = score(result, AnswerKey.model_validate(load_yaml(cfg.answer_key)))
    tel.seconds = round(time.perf_counter() - t0, 2)
    return result
