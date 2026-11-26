"""Web UI: view saved runs. No auth (prototype), no analysis (front ends only render a Run)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.web import views
from nparity import store
from nparity.config import load_thresholds
from nparity.models import Run

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter()


def runs_dir(request: Request) -> Path:
    return Path(getattr(request.app.state, "runs_dir", store.DEFAULT_DIR))


def load(request: Request, run_id: str) -> Run:
    try:
        return store.load(run_id, runs_dir(request))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No run {run_id}")


def thresholds(run: Run):
    return load_thresholds(backend_id=run.config.get("backend"))


@router.get("/", response_class=HTMLResponse)
def runs_page(request: Request):
    runs = [(r, views.counts(r)) for r in store.list_runs(runs_dir(request))]
    return TEMPLATES.TemplateResponse(request, "runs.html", {"runs": runs, "nav": "runs"})


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_page(request: Request, run_id: str):
    run = load(request, run_id)
    th = thresholds(run)
    body = TEMPLATES.get_template("_finding_body.html")
    sections = defaultdict(list)
    for f in run.findings:
        sections[f.status or "unsure"].append(views.finding_view(run, f, th))
    if sections["shown"]:                       # first regression opens server-side, the rest load via HTMX
        first = sections["shown"][0]
        first.body_html = body.render(v=first)
    rule_maps = sum(m.source == "rule" for m in run.endpoints) + sum(m.source == "rule" for m in run.fields)
    return TEMPLATES.TemplateResponse(request, "run.html", {
        "run": run, "nav": "run", "c": views.counts(run), "sections": sections,
        "missed": [d for d in (run.score.details if run.score else []) if not d["ok"]],
        "n_fields": len(run.fields), "rule_maps": rule_maps,
    })


@router.get("/runs/{run_id}/findings/{fid}", response_class=HTMLResponse)
def finding_partial(request: Request, run_id: str, fid: str):
    run = load(request, run_id)
    f = next((x for x in run.findings + run.errors if x.id == fid), None)
    if f is None:
        raise HTTPException(status_code=404, detail=f"No finding {fid}")
    return TEMPLATES.TemplateResponse(request, "_finding_body.html", {"v": views.finding_view(run, f, thresholds(run))})


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
