"""Run comparisons in the background and retain their recent console output."""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, Thread
from typing import Literal
from uuid import uuid4

import httpx
import yaml
from pydantic import BaseModel, Field, ValidationError

from app.web.run_sources import InputError, SourceInput, local_file, resolve_source
from nparity import pipeline, store
from nparity.config import Seeds, load_seeds
from nparity.evaluator.fake import FakeBackend
from nparity.models import AnswerKey
from nparity.retry import RetryPolicy
from nparity.tls import tls_verify

LOG = logging.getLogger(__name__)
HISTORY_LIMIT = 32


class RunInput(BaseModel):
    before: SourceInput
    after: SourceInput
    seeds: str = Field(default="", max_length=4096)
    intent: str = Field(default="", max_length=4096)
    backend: Literal["fake", "flash"] = "fake"
    name: str = Field(default="comparison", max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    score: bool = False


@dataclass
class Job:
    state: str = "running"
    lines: list[str] = field(default_factory=lambda: ["Starting comparison"])
    report_url: str | None = None


class RunJobs:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.lock = Lock()

    def start(self, inputs: RunInput, directory: Path) -> str | None:
        with self.lock:
            if any(job.state == "running" for job in self.jobs.values()):
                return None
            if len(self.jobs) == HISTORY_LIMIT:
                del self.jobs[next(iter(self.jobs))]
            job_id = uuid4().hex
            job = self.jobs[job_id] = Job()
            Thread(target=self.run, args=(job_id, job, inputs, directory), daemon=True).start()
            return job_id

    def status(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is not None:
                return {"state": job.state, "lines": list(job.lines), "report_url": job.report_url}
        return None

    def run(self, job_id: str, job: Job, inputs: RunInput, directory: Path) -> None:
        def progress(message: str) -> None:
            with self.lock:
                job.lines.append(message)

        try:
            report_id = compare(job_id, inputs, directory, progress)
        except InputError as exc:
            message = str(exc)
        except httpx.HTTPStatusError as exc:
            message = f"The API document returned HTTP {exc.response.status_code}. Check the source URL."
        except httpx.RequestError:
            message = "Could not reach the API document. Check the URL, network, and TLS settings."
        except (OSError, ValidationError, yaml.YAMLError):
            message = "Could not read the input files or save the report. Check file formats and permissions."
        except Exception:
            LOG.exception("Comparison %s failed", job_id)
            message = "Comparison failed during the last stage shown. See the server log for details."
        else:
            with self.lock:
                job.lines.append("Report saved")
                job.report_url = f"/runs/{report_id}"
                job.state = "complete"
            return
        with self.lock:
            job.lines.append(f"Error: {message}")
            job.state = "failed"


def compare(job_id: str, inputs: RunInput, directory: Path, progress: Callable[[str], None]) -> str:
    if inputs.backend == "flash" and not os.environ.get("FIREWORKS_API_KEY"):
        raise InputError("Set FIREWORKS_API_KEY in the server environment to use Flash.")
    defaults = pipeline.RunConfig("", "")
    seeds_path = local_file(inputs.seeds, {".yaml", ".yml"}) if inputs.seeds else defaults.seeds
    intent_path = local_file(inputs.intent, {".md", ".txt"}) if inputs.intent else None
    seeds = load_seeds(seeds_path)
    if not inputs.seeds:
        seeds.methods = ["GET"]
    ev = FakeBackend(AnswerKey()) if inputs.backend == "fake" and not inputs.score else None

    with httpx.Client(timeout=30, verify=tls_verify(), follow_redirects=True) as client:
        progress("Loading before source")
        before = resolve_source(client, inputs.before, "old")
        progress("Loading after source")
        after = resolve_source(client, inputs.after, "new")
        config = pipeline.RunConfig(
            before.base_url, after.base_url, intent=intent_path, seeds=seeds_path,
            answer_key=defaults.answer_key if inputs.score else None,
            backend=inputs.backend, name=f"{inputs.name}-{job_id[:12]}",
        )
        options = {"specs": (before.spec, after.spec), "request_seeds": seeds, "progress": progress}
        if before.capture is None and after.capture is None:
            run = pipeline.run(config, client, ev, **options)
        elif before.capture is not None and after.capture is not None:
            captures = {"old.capture.invalid": before.capture, "new.capture.invalid": after.capture}

            def serve_capture(request: httpx.Request) -> httpx.Response:
                status, body = captures[request.url.host]
                return httpx.Response(status, json=body)

            config.retry = RetryPolicy(statuses=frozenset())
            options["request_seeds"] = Seeds()
            with httpx.Client(transport=httpx.MockTransport(serve_capture)) as offline:
                run = pipeline.run(config, offline, ev, **options)
            run.config.update(old=before.label, new=after.label)
        else:
            raise InputError("Choose saved responses for both sides to compare captures. Specs from a manifest can be combined with live API sources.")

    progress(f"Saving report with {len(run.findings)} findings and {len(run.errors)} errors")
    store.save(run, directory)
    return run.id
