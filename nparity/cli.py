"""nparity CLI: run, show, runs. Renders saved runs only; no analysis here."""

from __future__ import annotations

import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import httpx
import typer
import yaml

from nparity import cli_jobs, headers, pipeline, seed_generation, seed_samples, store
from nparity.cli_output import (
    EXIT_GATE, AgentGroup, FindingFilter, Gate, compact_run, emit_json, error_record, gate_error, gate_failures,
)
from nparity.config import Seeds, load_seeds
from nparity.evaluator.profiles import load_profile
from nparity.flow_report import markdown
from nparity.flow_score import key_skeleton
from nparity.openapi import endpoints, load_spec
from nparity.request_samples import load_request_pairs
from nparity.tls import tls_verify
from nparity.models import Run
from nparity.review import finding_key

app = typer.Typer(cls=AgentGroup, add_completion=False, no_args_is_help=True, help="Will we break anything?")
WEB = os.environ.get("NPARITY_WEB", "http://localhost:8000")


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


class ProgressFormat(StrEnum):
    NONE = "none"
    JSONL = "jsonl"


FormatOption = Annotated[OutputFormat | None, typer.Option("--format", help="Output format (default: text)")]


@app.callback()
def cli_options(ctx: typer.Context, output_format: FormatOption = None) -> None:
    ctx.obj = output_format


def _as_json(ctx: typer.Context, output_format: OutputFormat | None) -> bool:
    return (output_format or ctx.find_root().obj) == OutputFormat.JSON


def _saved_run(run: Run, path: Path) -> dict:
    return {**json.loads(run.model_dump_json()), "saved_to": str(path), "report_url": f"{WEB}/runs/{run.id}"}


def _line(f) -> str:
    p = f"p={f.p:.3f}" if f.p is not None else "p=—"
    reason = f"  {f.reason}" if f.reason else ""
    return f"  {f.endpoint:<22} {f.path:<14} {f.kind:<20} {p}{reason}"


def summary(r: Run) -> str:
    if r.flow_mapping is not None:
        return markdown(r).rstrip()
    by = lambda status: [f for f in r.findings if f.status == status]  # noqa: E731
    reg, uns, acc = by("shown"), by("unsure"), by("accepted")
    out = [
        f"Run {r.id}  ({r.config.get('backend')})",
        f"Regressions: {len(reg)}   Unsure: {len(uns)}   Intended: {len(acc)}   "
        f"Noise: {len(r.noise)}   Errors: {len(r.errors)}",
    ]
    if banner := r.basic_checks_summary():
        out.insert(1, banner)
    if notice := r.independent_data_summary():
        out.insert(1, notice)
    if r.contract:
        out.append(f"Declared differences: {len(r.contract)}")
    if reg:
        out += ["", "Regressions"] + [_line(f) for f in reg]
    if uns:
        out += ["", "Unsure"] + [_line(f) for f in uns]
    if r.errors:
        out += ["", "Errors"] + [f"  {e.endpoint:<22} {e.reason}" for e in r.errors]
    if r.score:
        s = r.score
        out += ["", f"Answer key: {s.correct}/{s.total} correct · {s.unsure} unsure · "
                    f"{s.false_regressions} false regressions"]
        out += [f"  #{d['n']} {d['endpoint']} {d['path']}: expected {d['expect']}, got {d['got']}"
                for d in s.details if not d["ok"]]
    t = r.telemetry
    out += [f"Decisions: {t.rule_decisions} by rule, {t.llm_calls} by LLM · retries {t.retries} · "
            f"{t.seconds:.1f} s · ${t.cost_usd:.4f}"]
    return "\n".join(out)


@app.command("seeds")
def write_seeds(
    ctx: typer.Context,
    spec: str = typer.Argument(..., help="OpenAPI or Swagger document URL or file"),
    out: Path = typer.Option(Path("seeds.yaml"), "--out", help="Output YAML file"),
    manual: Path | None = typer.Option(None, "--manual", help="Existing seeds to preserve and override generated values"),
    samples: Path | None = typer.Option(None, "--samples", help="Saved request examples or a capture manifest"),
    output_format: FormatOption = None,
) -> None:
    """Generate seeds with provenance from an API specification."""
    with httpx.Client(timeout=30, verify=tls_verify(), follow_redirects=True,
                      headers={"User-Agent": headers.API_USER_AGENT}) as client:
        try:
            document = load_spec(client, "", spec)
            if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
                raise ValueError("The spec must contain an OpenAPI paths section.")
            seeds = load_seeds(manual) if manual else Seeds()
            operations = endpoints(document)
            seeds = seed_generation.fill_gaps(seeds, seed_generation.from_spec(operations))
            if samples:
                seed_samples.apply(samples, operations, seeds)
        except (ValueError, TypeError, KeyError, OSError, httpx.HTTPError, yaml.YAMLError) as exc:
            if _as_json(ctx, output_format) and isinstance(exc, httpx.HTTPError):
                raise
            raise typer.BadParameter(str(exc)) from exc
    out.write_text(yaml.safe_dump(seeds.model_dump(mode="json", exclude_none=True, exclude_defaults=True), sort_keys=False),
                   encoding="utf-8")
    if _as_json(ctx, output_format):
        data = json.loads(seeds.model_dump_json(exclude_none=True, exclude_defaults=True))
        emit_json({"saved_to": str(out), "seeds": data})
    else:
        typer.echo(f"Saved {out}")


@app.command()
def run(
    ctx: typer.Context,
    old: str | None = typer.Option(None, help="Old service base URL, e.g. http://localhost:8000/v1"),
    new: str | None = typer.Option(None, help="New service base URL"),
    old_spec: str | None = typer.Option(None, help="Old OpenAPI/Swagger spec: URL or file (default <old>/openapi.json)"),
    new_spec: str | None = typer.Option(None, help="New spec: URL or file (default <new>/openapi.json)"),
    old_header: list[str] = typer.Option([], "--old-header", help="Repeatable. 'Name: env:VAR', value read from the environment"),
    new_header: list[str] = typer.Option([], "--new-header", help="Repeatable. 'Name: env:VAR'"),
    intent: Path = typer.Option(Path("fixtures/intent.md")),
    seeds: Path | None = typer.Option(None, help="Optional YAML overrides for generated seeds"),
    discover_from: list[str] = typer.Option([], "--discover-from", help="Allowlisted GET operation, e.g. 'GET /pets'. Repeatable."),
    seed_examples: Path | None = typer.Option(None, "--seed-samples", help="Saved request examples or captures to use as seeds"),
    samples: Path | None = typer.Option(None, "--samples", help="YAML/JSON file of explicit GET request pairs for basic checks"),
    contract_only: bool = typer.Option(False, "--contract-only", help="Compare specs without replaying API calls"),
    flow_mapping: bool = typer.Option(False, "--flow-mapping", help="Suggest operation flows from two specs"),
    flow_key: Path | None = typer.Option(None, "--flow-key", help="Score against a confirmed flow answer key"),
    answer_key: Path | None = typer.Option(Path("fixtures/answer_key.yaml")),
    backend: str = typer.Option(os.environ.get("NPARITY_LLM", "fake"), help="fake | flash"),
    name: str = typer.Option("toy"),
    score: bool = typer.Option(True, "--score/--no-score", help="Score against --answer-key"),
    runs_dir: Path = typer.Option(store.DEFAULT_DIR),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan from specs and seeds without replay, discovery, or model calls"),
    compact: bool = typer.Option(False, "--compact", help="Return counts and finding IDs in JSON"),
    fail_on: list[Gate] = typer.Option([], "--fail-on", help="Exit 5 after saving when the selected condition occurs. Repeatable"),
    progress: ProgressFormat = typer.Option(ProgressFormat.NONE, "--progress", help="Write progress events to stderr"),
    detach: bool = typer.Option(False, "--detach", help="Start in the background and poll with status"),
    output_format: FormatOption = None,
) -> None:
    as_json = _as_json(ctx, output_format)
    try:
        cli_jobs.validate_id(name)
        old_source = old or (old_spec if flow_mapping else None)
        new_source = new or (new_spec if flow_mapping else None)
        if not old_source or not new_source:
            raise ValueError("Supply --old and --new, or give both spec locations with --flow-mapping.")
        cfg = pipeline.RunConfig(
            old=old_source, new=new_source, old_spec=old_spec, new_spec=new_spec, intent=intent, seeds=seeds,
            answer_key=answer_key if score else None, backend=backend, name=name,
            old_headers=list(old_header), new_headers=list(new_header), discover_from=discover_from,
            seed_samples=seed_examples, contract_only=contract_only and not flow_mapping,
            flow_mapping=flow_mapping, flow_key=flow_key,
        )
        if backend not in {"fake", "flash"}:
            raise ValueError("Choose fake or flash for --backend.")
        if flow_key is not None and not flow_mapping:
            raise ValueError("--flow-key requires --flow-mapping.")
        if flow_mapping and fail_on:
            raise ValueError("--fail-on applies to replay findings. Flow mappings require review.")
        if backend == "flash" and not dry_run and not cfg.contract_only:
            key_env = load_profile("config/profiles/flash.yaml").provider.api_key_env
            if not os.environ.get(key_env):
                raise ValueError(f"Set {key_env} to use Flash.")
        if dry_run and detach:
            raise ValueError("Choose either --dry-run or --detach.")
        headers.resolve(cfg.old_headers, "old")
        headers.resolve(cfg.new_headers, "new")
        if samples is not None and not flow_mapping:
            if cfg.contract_only:
                raise ValueError("Choose either --samples or --contract-only.")
            cfg.sample_requests = load_request_pairs(samples)
    except (ValueError, OSError, yaml.YAMLError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if dry_run:
        with httpx.Client(timeout=30, verify=tls_verify(), follow_redirects=True,
                          headers={"User-Agent": headers.API_USER_AGENT}) as client:
            plan = pipeline.plan(cfg, client)
        if as_json:
            emit_json(plan)
        else:
            typer.echo(f"Dry run · {plan['requests']} planned requests")
            for row in plan["endpoints"]:
                sources = ", ".join(row["seed_sources"]) or "no seeds needed"
                details = row["reason"] or f"{row['requests']} requests · {sources}"
                typer.echo(f"{row['endpoint']} · {details}")
            for old_op, candidates in plan.get("flow_candidates", {}).items():
                typer.echo(f"{old_op} · {len(candidates)} flow candidates")
        return

    job = cli_jobs.start(runs_dir, name) if detach or progress == ProgressFormat.JSONL else None
    if job is not None:
        cfg.run_id = job.data["run_id"]
        if progress == ProgressFormat.JSONL:
            emit_json(job.data["events"][0], stderr=True)
    if detach:
        try:
            cli_jobs.detach(cfg, runs_dir, fail_on)
        except Exception as exc:
            job.fail(*error_record(exc))
            raise
        if as_json:
            emit_json(job.data)
        else:
            typer.echo(f"Queued {cfg.run_id}")
        return

    def report(event: str, message: str, **state) -> None:
        if job is not None:
            emit_json(job.record(event, message, **state), stderr=True)

    report("started", "Run started.", state="running", pid=os.getpid())
    try:
        with httpx.Client(timeout=30, verify=tls_verify(), follow_redirects=True,
                          headers={"User-Agent": headers.API_USER_AGENT}) as client:
            r, path = cli_jobs.execute(cfg, runs_dir, client, lambda message: report("progress", message))
    except KeyboardInterrupt:
        if job is not None:
            job.fail(130, cli_jobs.INTERRUPTED)
        raise
    except Exception as exc:
        if job is not None:
            job.fail(*error_record(exc))
        raise
    failures = gate_failures(r, fail_on)
    if job is not None:
        emit_json(job.complete(path, failures), stderr=True)
    if as_json:
        emit_json({**compact_run(r), "saved_to": str(path), "report_url": f"{WEB}/runs/{r.id}"}
                  if compact else _saved_run(r, path))
    else:
        typer.echo(summary(r))
        typer.echo(f"\nSaved {path}\n{WEB}/runs/{r.id}")
    if failures:
        error = gate_error(r.id, failures)
        if as_json or progress == ProgressFormat.JSONL:
            emit_json({"error": error}, stderr=True)
        else:
            typer.echo(error["message"], err=True)
        raise typer.Exit(EXIT_GATE)


@app.command()
def status(ctx: typer.Context, run_id: str, runs_dir: Path = typer.Option(store.DEFAULT_DIR),
           after: int = typer.Option(0, "--after", min=0, help="Show events after this sequence number"),
           wait: float = typer.Option(0, "--wait", min=0, max=60, help="Seconds to wait for a new event"),
           output_format: FormatOption = None) -> None:
    """Poll a tracked run by ID without restarting it."""
    data = cli_jobs.read(runs_dir, run_id, after=after, wait=wait)
    data.pop("pid", None)
    if data.get("saved_to"):
        data["report_url"] = f"{WEB}/runs/{run_id}"
    if _as_json(ctx, output_format):
        emit_json(data)
    else:
        typer.echo(f"{run_id} · {data['state']}")
        for event in data["events"]:
            typer.echo(f"{event['seq']} {event['message']}")


@app.command()
def show(ctx: typer.Context, run_id: str, runs_dir: Path = typer.Option(store.DEFAULT_DIR),
         compact: bool = typer.Option(False, "--compact", help="Return counts and finding IDs in JSON"),
         statuses: list[FindingFilter] = typer.Option([], "--status", help="Filter JSON findings by status. Repeatable"),
         endpoint: str | None = typer.Option(None, "--endpoint", help="Filter JSON findings by exact method and path"),
         limit: int = typer.Option(50, "--limit", min=1, max=500, help="Maximum findings in a compact page"),
         offset: int = typer.Option(0, "--offset", min=0, help="Skip findings in a compact page"),
         output_format: FormatOption = None) -> None:
    r = store.load(cli_jobs.validate_id(run_id), runs_dir)
    if _as_json(ctx, output_format):
        path = runs_dir / f"{run_id}.yaml"
        if compact or statuses or endpoint is not None or offset or limit != 50:
            emit_json({**compact_run(r, statuses, endpoint, limit, offset),
                       "saved_to": str(path), "report_url": f"{WEB}/runs/{r.id}"})
        else:
            emit_json(_saved_run(r, path))
    else:
        typer.echo(summary(r))


@app.command()
def report(ctx: typer.Context, run_id: str, runs_dir: Path = typer.Option(store.DEFAULT_DIR),
           output_format: FormatOption = None) -> None:
    """Export a saved flow report as Markdown or JSON."""
    saved = store.load(cli_jobs.validate_id(run_id), runs_dir)
    if _as_json(ctx, output_format):
        emit_json(_saved_run(saved, runs_dir / f"{run_id}.yaml"))
    else:
        typer.echo(markdown(saved), nl=False)


@app.command("key")
def write_flow_key(ctx: typer.Context, run_id: str, out: Path = typer.Option(..., "--out"),
                   runs_dir: Path = typer.Option(store.DEFAULT_DIR), output_format: FormatOption = None) -> None:
    """Write a draft flow answer key for engineer review."""
    result = store.load(cli_jobs.validate_id(run_id), runs_dir).flow_mapping
    if result is None:
        raise typer.BadParameter("Choose a saved flow mapping run.")
    data = key_skeleton(result).model_dump(mode="json", exclude_defaults=True)
    data = {"version": 1, "confirmed_by": None, **data}
    with out.open("x", encoding="utf-8") as file:
        yaml.safe_dump(data, file, sort_keys=False, allow_unicode=True)
    if _as_json(ctx, output_format):
        emit_json({"saved_to": str(out), "key": data})
    else:
        typer.echo(f"Saved {out}")


@app.command()
def finding(ctx: typer.Context, run_id: str, finding_id: str, runs_dir: Path = typer.Option(store.DEFAULT_DIR),
            output_format: FormatOption = None) -> None:
    """Fetch one finding and its response samples by ID or stable key."""
    r = store.load(cli_jobs.validate_id(run_id), runs_dir)
    match = next((f for f in r.findings + r.errors if finding_id in (f.id, finding_key(f))), None)
    if match is None:
        raise FileNotFoundError(f"No finding {finding_id!r} in run {run_id!r}.")
    if _as_json(ctx, output_format):
        emit_json({"run_id": r.id, "key": finding_key(match), "finding": json.loads(match.model_dump_json())})
    else:
        typer.echo(_line(match))


@app.command()
def runs(ctx: typer.Context, runs_dir: Path = typer.Option(store.DEFAULT_DIR), output_format: FormatOption = None) -> None:
    saved = store.list_runs(runs_dir)
    if _as_json(ctx, output_format):
        emit_json([
            {
                "id": r.id,
                "started_at": r.started_at.isoformat(),
                "backend": r.config.get("backend"),
                "regressions": sum(f.status == "shown" for f in r.findings),
                "score": {"correct": r.score.correct, "total": r.score.total} if r.score else None,
                "report_url": f"{WEB}/runs/{r.id}",
            }
            for r in saved
        ])
        return
    for r in saved:
        s = f"{r.score.correct}/{r.score.total}" if r.score else "—"
        reg = sum(f.status == "shown" for f in r.findings)
        typer.echo(f"{r.id:<32} {r.config.get('backend', ''):<40} regressions {reg}  key {s}")


@app.command()
def freeze(ctx: typer.Context, run_id: str, as_id: str = typer.Option("demo", "--as"),
           runs_dir: Path = typer.Option(store.DEFAULT_DIR), output_format: FormatOption = None) -> None:
    """Save a copy of a run under a fixed id (default: demo), for the demo page."""
    r = store.load(cli_jobs.validate_id(run_id), runs_dir)
    r.id = cli_jobs.validate_id(as_id)
    path = store.save(r, runs_dir)
    if _as_json(ctx, output_format):
        emit_json(_saved_run(r, path))
    else:
        typer.echo(f"Saved {path}\n{WEB}/runs/{as_id}")


if __name__ == "__main__":
    app()
