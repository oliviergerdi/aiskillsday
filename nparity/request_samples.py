"""Read explicit GET request pairs for a comparison without API specs."""

from pathlib import Path

from pydantic import TypeAdapter

from nparity.config import load_yaml
from nparity.models import RequestPair
from nparity.replay import path_params


def load_request_pairs(path: Path) -> list[RequestPair]:
    data = load_yaml(path)
    pairs = TypeAdapter(list[RequestPair]).validate_python(data.get("requests") if isinstance(data, dict) else data)
    for pair in pairs:
        for request in (pair.old, pair.new):
            if request.method != "GET" or request.body is not None:
                raise ValueError("Sample files can replay GET requests only.")
            if (not request.path.startswith("/") or request.path.startswith("//")
                    or "?" in request.path or "#" in request.path):
                raise ValueError("Sample paths must be relative to the API base URL. Put query values in params.")
            if not set(path_params(request.path)) <= request.params.keys():
                raise ValueError(f"Missing path parameter in sample: {request.path}")
    return pairs
