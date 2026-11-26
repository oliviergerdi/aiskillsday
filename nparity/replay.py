"""Send each request to old, and its mapped counterpart to new."""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from nparity.models import EndpointMap, HttpResult, Request, Sample
from nparity.retry import RetryExhausted, RetryPolicy, retry_call

PARAM = re.compile(r"{(\w+)}")


def path_params(template: str) -> list[str]:
    return PARAM.findall(template)


def fill(req: Request) -> tuple[str, dict[str, Any]]:
    """Substitute path params; everything else becomes the query string."""
    names = set(path_params(req.path))
    path = PARAM.sub(lambda m: str(req.params[m.group(1)]), req.path)
    return path, {k: v for k, v in req.params.items() if k not in names}


def to_new(req: Request, m: EndpointMap) -> Request | None:
    if m.new is None or m.status == "unmapped":
        return None
    method, new_path = m.new.split(" ", 1)
    old_names, new_names = path_params(req.path), path_params(new_path)
    params = {k: v for k, v in req.params.items() if k not in old_names}
    for old_name, new_name in zip(old_names, new_names):       # path params carried over by position
        params[new_name] = req.params[old_name]
    return Request(method=method, path=new_path, params=params, body=req.body)


class _Counter:
    def __init__(self) -> None:
        self.n = 0
        self._lock = threading.Lock()

    def __call__(self, *_: Any) -> None:
        with self._lock:
            self.n += 1


def send(client: httpx.Client, base: str, req: Request, policy: RetryPolicy,
         on_retry: Any = None) -> HttpResult:
    path, query = fill(req)
    url = base.rstrip("/") + path

    def call() -> httpx.Response:
        r = client.request(req.method, url, params=query or None,
                           json=req.body if req.body is not None else None)   # timeout lives on the client
        if r.status_code in policy.statuses:
            r.raise_for_status()
        return r

    try:
        r = retry_call(call, policy, on_retry=on_retry)
    except RetryExhausted as e:
        return HttpResult(status=None, error=str(e))
    except httpx.HTTPError as e:
        return HttpResult(status=None, error=f"{type(e).__name__}: {e}")
    try:
        body: Any = r.json()
    except ValueError:
        body = r.text or None
    return HttpResult(status=r.status_code, body=body)


def replay(reqs: list[Request], emap: dict[str, EndpointMap], client: httpx.Client, old_base: str,
           new_base: str, policy: RetryPolicy = RetryPolicy(), workers: int = 8) -> tuple[list[Sample], int]:
    """Returns (samples in request order, number of retries). Errors are results, never exceptions."""
    retries = _Counter()

    def one(req: Request) -> Sample:
        old = send(client, old_base, req, policy, retries)
        m = emap.get(req.endpoint)
        new_req = to_new(req, m) if m else None
        new = (send(client, new_base, new_req, policy, retries) if new_req
               else HttpResult(status=None, error="unmapped"))
        return Sample(old_request=req, new_request=new_req, old=old, new=new)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        samples = list(pool.map(one, reqs))
    return samples, retries.n
