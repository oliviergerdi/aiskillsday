"""Web UI for starting comparisons and viewing saved runs."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.web import views
from app.web.run_jobs import RunInput, RunJobs
from nparity import store
from nparity.config import load_thresholds
from nparity.models import Run

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


def thresholds(run: Run):
    return load_thresholds(backend_id=run.config.get("backend"))


def local_run_request(request: Request) -> None:
    origin = request.headers.get("origin")
    expected = f"{request.url.scheme}://{request.url.netloc}"
    local = request.client and request.client.host in {"127.0.0.1", "::1"}
    if not local or request.url.hostname not in {"localhost", "127.0.0.1", "::1"} or (origin and origin != expected):
        raise HTTPException(status_code=403, detail="Open nParity on localhost to start a comparison.")


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
    job_id = jobs.start(inputs, runs_dir(request))
    if job_id is None:
        raise HTTPException(status_code=409, detail="A comparison is already running. Try again when it finishes.")
    return {"job_url": f"/run-jobs/{job_id}"}


@router.get("/run-jobs/{job_id}", dependencies=[Depends(local_run_request)])
def run_status(job_id: str):
    job = jobs.status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="This run console is no longer available.")
    return job


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
    groups = {k: views.group_findings(sections[k]) for k in ("shown", "unsure", "accepted")}
    if groups["shown"]:                         # first regression opens server-side, the rest load via HTMX
        first = groups["shown"][0].items[0]
        first.body_html = body.render(v=first)
    rule_maps = sum(m.source == "rule" for m in run.endpoints) + sum(m.source == "rule" for m in run.fields)
    counts = views.counts(run)
    return TEMPLATES.TemplateResponse(request, "run.html", {
        "run": run, "nav": "run", "c": counts, "groups": groups,
        "verdict": views.verdict(counts), "empty": not run.findings,
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
