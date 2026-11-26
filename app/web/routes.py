"""Web UI for starting comparisons and viewing saved runs."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates

from app.web import views
from app.web.configs import list_configs, load_config
from app.web.run_jobs import RunInput, RunJobs
from nparity import store
from nparity.config import load_thresholds
from nparity.flow_report import markdown
from nparity.models import Run
from typing import Literal

from pydantic import BaseModel, Field

from nparity.review import (Ledger, agreement, compare, finding_key, open_counts, review_states, scope_of, stale,
                            verdict)

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
TEMPLATES.env.filters["run_name"] = views.run_name
TEMPLATES.env.filters["backend_label"] = views.backend_label
router = APIRouter()
jobs = RunJobs()


def runs_dir(request: Request) -> Path:
    return Path(getattr(request.app.state, "runs_dir", store.DEFAULT_DIR))


def load(request: Request, run_id: str) -> Run:
    try:
        return store.load(run_id, runs_dir(request))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No run {run_id}")


def comparisons_dir(request: Request) -> Path:
    return Path(getattr(request.app.state, "comparisons_dir", "comparisons"))


def ledger(request: Request) -> Ledger:
    return Ledger.load(getattr(request.app.state, "ledger_path", "accepted.yaml"))


def thresholds(run: Run):
    return load_thresholds(backend_id=run.config.get("backend"))


def local_run_request(request: Request) -> None:
    origin = request.headers.get("origin")
    expected = f"{request.url.scheme}://{request.url.netloc}"
    local = request.client and request.client.host in {"127.0.0.1", "::1"}
    if not local or request.url.hostname not in {"localhost", "127.0.0.1", "::1"} or (origin and origin != expected):
        raise HTTPException(status_code=403, detail="Open nParity on localhost for this action.")


@router.get("/compare", response_class=HTMLResponse)
def new_run(request: Request):
    fixtures = Path(__file__).parents[2] / "fixtures"

    def intent_text(path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    presets = {"toy": intent_text(fixtures / "intent.md"),
               "petstore": intent_text(fixtures / "petstore" / "intent.md")}
    return TEMPLATES.TemplateResponse(request, "new_run.html", {"nav": "new", "presets": presets})


@router.post("/run-jobs", status_code=202, dependencies=[Depends(local_run_request)])
def start_run(request: Request, inputs: RunInput):
    job_id = jobs.start(inputs, runs_dir(request), comparisons_dir(request))
    if job_id is None:
        raise HTTPException(status_code=409, detail="A comparison is already running. Try again when it finishes.")
    return {"job_url": f"/run-jobs/{job_id}"}


@router.get("/run-jobs/{job_id}", dependencies=[Depends(local_run_request)])
def run_status(job_id: str):
    job = jobs.status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="This run console is no longer available.")
    return job


@router.get("/comparisons", dependencies=[Depends(local_run_request)])
def comparisons_list(request: Request):
    return [{"name": c.name, "backend": c.backend, "before": c.before.source, "after": c.after.source}
            for c in list_configs(comparisons_dir(request))]


@router.get("/comparisons/{name}", dependencies=[Depends(local_run_request)])
def comparison_detail(request: Request, name: str):
    try:
        config = load_config(name, comparisons_dir(request))
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail=f"No configuration {name}")
    led = ledger(request)
    runs = [r for r in store.list_runs(runs_dir(request)) if r.config.get("config") == name]
    return {"config": config.model_dump(mode="json", exclude={"save_config", "baseline"}),
            "runs": [{"id": r.id, "started_at": r.started_at.isoformat(), "open": open_counts(r, led)["open"]}
                     for r in runs]}


@router.get("/", response_class=HTMLResponse)
def runs_page(request: Request):
    runs = [(r, views.counts(r)) for r in store.list_runs(runs_dir(request))]
    return TEMPLATES.TemplateResponse(request, "runs.html", {"runs": runs, "nav": "runs"})


@router.delete("/runs/{run_id}", dependencies=[Depends(local_run_request)])
def delete_run(request: Request, run_id: str) -> Response:
    try:
        store.delete(run_id, runs_dir(request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Invalid run ID.") from exc
    return Response(headers={"HX-Redirect": "/"})


def baseline_for(request: Request, run: Run, requested: str | None):
    """(baseline run or None, same-scope candidates). `requested` ('' = none) overrides the stored one."""
    candidates = [r for r in store.list_runs(runs_dir(request)) if scope_of(r) == scope_of(run) and r.id != run.id]
    wanted = run.config.get("baseline") if requested is None else requested
    base = next((r for r in candidates if r.id == wanted), None) if wanted else None
    return base, candidates


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_page(request: Request, run_id: str, baseline: str | None = None):
    run = load(request, run_id)
    if run.flow_mapping is not None:
        return TEMPLATES.TemplateResponse(request, "flow_run.html", {"run": run, "nav": "run"})
    th = thresholds(run)
    led = ledger(request)
    base, candidates = baseline_for(request, run, baseline)
    comparison = compare(run, base) if base else None
    states = review_states(run, led)
    sections = views.build_sections(run, states, th, comparison)
    groups = {k: views.group_findings(v) for k, v in sections.items()}
    first = (sections["regression"] or sections["rejected"] or [None])[0]
    if first is not None:                      # first open regression opens server-side, the rest via HTMX
        first.body_html = TEMPLATES.get_template("_finding_body.html").render(v=first)
    rule_maps = sum(m.source == "rule" for m in run.endpoints) + sum(m.source == "rule" for m in run.fields)
    return TEMPLATES.TemplateResponse(request, "run.html", {
        "run": run, "nav": "run", "c": views.review_counts(sections, run), "sections": sections,
        "groups": groups, "verdict": verdict(run, led), "empty": not run.findings,
        "missed": [d for d in (run.score.details if run.score else []) if not d["ok"]],
        "n_fields": len(run.fields), "rule_maps": rule_maps,
        "comparison": comparison, "baseline": base, "candidates": candidates,
        "scope": scope_of(run), "agreement": agreement(run, led),
    })


def find(run: Run, fid: str):
    f = next((x for x in run.findings + run.errors if x.id == fid), None)
    if f is None:
        raise HTTPException(status_code=404, detail=f"No finding {fid}")
    return f


@router.get("/runs/{run_id}/findings/{fid}", response_class=HTMLResponse)
def finding_partial(request: Request, run_id: str, fid: str):
    run = load(request, run_id)
    v = views.review_view(run, find(run, fid), thresholds(run), review_states(run, ledger(request)))
    return TEMPLATES.TemplateResponse(request, "_finding_body.html", {"v": v})


@router.get("/runs/{run_id}/report.md", response_class=PlainTextResponse)
def flow_report(request: Request, run_id: str) -> str:
    run = load(request, run_id)
    if run.flow_mapping is None:
        raise HTTPException(status_code=404, detail="This run has no flow mapping.")
    return markdown(run)


@router.get("/runs/{run_id}/signoff", response_class=HTMLResponse)
def signoff_page(request: Request, run_id: str):
    run = load(request, run_id)
    th = thresholds(run)
    led = ledger(request)
    base, _ = baseline_for(request, run, None)
    states = review_states(run, led)
    sections = views.build_sections(run, states, th, compare(run, base) if base else None)
    return TEMPLATES.TemplateResponse(request, "signoff.html", {
        "run": run, "nav": "run", "verdict": verdict(run, led), "oc": open_counts(run, led),
        "open_items": sections["rejected"] + sections["regression"] + sections["unsure"],
        "accepted": sections["accepted"], "intended": sections["intended"],
        "stale": stale(run, led), "th": th, "baseline": base,
        "comparison": compare(run, base) if base else None, "scope": scope_of(run),
        "agreement": agreement(run, led),
    })


class DecisionIn(BaseModel):
    decision: Literal["accept", "reject"]
    by: str = Field(min_length=1, max_length=80, pattern=r"\S")
    note: str = Field(default="", max_length=500)


@router.post("/runs/{run_id}/findings/{fid}/decision", dependencies=[Depends(local_run_request)])
def record_decision(request: Request, run_id: str, fid: str, body: DecisionIn):
    run = load(request, run_id)
    f = find(run, fid)
    if f.status == "error":
        raise HTTPException(status_code=422, detail="Errors need a rerun, not a decision.")
    entry = ledger(request).record(run, f, body.decision, body.by, body.note)
    return {"entry": entry.model_dump(mode="json")}


@router.delete("/runs/{run_id}/findings/{fid}/decision", dependencies=[Depends(local_run_request)])
def undo_decision(request: Request, run_id: str, fid: str):
    run = load(request, run_id)
    return {"removed": ledger(request).remove(scope_of(run), finding_key(find(run, fid)))}


@router.get("/runs/{run_id}/mapping", response_class=HTMLResponse)
def mapping_page(request: Request, run_id: str):
    run = load(request, run_id)
    by_endpoint = defaultdict(list)
    for fm in run.fields:
        by_endpoint[fm.endpoint].append(fm)
    detailed = {ep: fms for ep, fms in by_endpoint.items() if any(x.source != "rule" or x.new != x.old for x in fms)}
    plain = {ep: len(fms) for ep, fms in by_endpoint.items() if ep not in detailed}
    new_of = {m.old: m.new for m in run.endpoints}
    return TEMPLATES.TemplateResponse(request, "mapping.html", {
        "run": run, "nav": "mapping", "detailed": detailed, "plain": plain, "new_of": new_of,
        "declared": views.declared_types(run),
    })
