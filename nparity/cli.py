"""nparity CLI: run, show, runs. Renders saved runs only; no analysis here."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import typer

from nparity import headers, pipeline, store
from nparity.tls import tls_verify
from nparity.models import Run

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Will we break anything?")
WEB = os.environ.get("NPARITY_WEB", "http://localhost:8000")


def _line(f) -> str:
    p = f"p={f.p:.3f}" if f.p is not None else "p=—"
    reason = f"  {f.reason}" if f.reason else ""
    return f"  {f.endpoint:<22} {f.path:<14} {f.kind:<20} {p}{reason}"


def summary(r: Run) -> str:
    by = lambda status: [f for f in r.findings if f.status == status]  # noqa: E731
    reg, uns, acc = by("shown"), by("unsure"), by("accepted")
    out = [
        f"Run {r.id}  ({r.config.get('backend')})",
        f"Regressions: {len(reg)}   Unsure: {len(uns)}   Intended: {len(acc)}   "
        f"Noise: {len(r.noise)}   Errors: {len(r.errors)}",
    ]
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


@app.command()
def run(
    old: str = typer.Option(..., help="Old service base URL, e.g. http://localhost:8000/v1"),
    new: str = typer.Option(..., help="New service base URL"),
    old_spec: str | None = typer.Option(None, help="Old OpenAPI/Swagger spec: URL or file (default <old>/openapi.json)"),
    new_spec: str | None = typer.Option(None, help="New spec: URL or file (default <new>/openapi.json)"),
    old_header: list[str] = typer.Option([], "--old-header", help="Repeatable. 'Name: env:VAR', value read from the environment"),
    new_header: list[str] = typer.Option([], "--new-header", help="Repeatable. 'Name: env:VAR'"),
    intent: Path = typer.Option(Path("fixtures/intent.md")),
    seeds: Path = typer.Option(Path("fixtures/seeds.yaml")),
    answer_key: Path | None = typer.Option(Path("fixtures/answer_key.yaml")),
    backend: str = typer.Option(os.environ.get("NPARITY_LLM", "fake"), help="fake | flash"),
    name: str = typer.Option("toy"),
    score: bool = typer.Option(True, "--score/--no-score", help="Score against --answer-key"),
    runs_dir: Path = typer.Option(store.DEFAULT_DIR),
) -> None:
    cfg = pipeline.RunConfig(old=old, new=new, old_spec=old_spec, new_spec=new_spec, intent=intent, seeds=seeds,
                             answer_key=answer_key if score else None, backend=backend, name=name,
                             old_headers=list(old_header), new_headers=list(new_header))
    try:
        headers.resolve(cfg.old_headers, "old")
        headers.resolve(cfg.new_headers, "new")
    except headers.HeaderError as exc:
        raise typer.BadParameter(str(exc)) from exc
    with httpx.Client(timeout=30, verify=tls_verify(), follow_redirects=True) as client:
        r = pipeline.run(cfg, client)
    path = store.save(r, runs_dir)
    typer.echo(summary(r))
    typer.echo(f"\nSaved {path}\n{WEB}/runs/{r.id}")


@app.command()
def show(run_id: str, runs_dir: Path = typer.Option(store.DEFAULT_DIR)) -> None:
    typer.echo(summary(store.load(run_id, runs_dir)))


@app.command()
def runs(runs_dir: Path = typer.Option(store.DEFAULT_DIR)) -> None:
    for r in store.list_runs(runs_dir):
        s = f"{r.score.correct}/{r.score.total}" if r.score else "—"
        reg = sum(f.status == "shown" for f in r.findings)
        typer.echo(f"{r.id:<32} {r.config.get('backend', ''):<40} regressions {reg}  key {s}")


@app.command()
def freeze(run_id: str, as_id: str = typer.Option("demo", "--as"),
           runs_dir: Path = typer.Option(store.DEFAULT_DIR)) -> None:
    """Save a copy of a run under a fixed id (default: demo), for the demo page."""
    r = store.load(run_id, runs_dir)
    r.id = as_id
    path = store.save(r, runs_dir)
    typer.echo(f"Saved {path}\n{WEB}/runs/{as_id}")


if __name__ == "__main__":
    app()
