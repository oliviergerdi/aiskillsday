"""PRD 0002: auth headers as `Name: env:VAR`, values from the environment, never stored."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.web.configs import RunInput, save_config
from app.web.run_sources import SourceInput
from nparity import headers, pipeline, store
from nparity.retry import RetryPolicy

SECRET_OLD, SECRET_NEW = "s3cret-old-value", "s3cret-new-value"


def test_parse_and_names():
    assert headers.parse("Authorization: env:OLD_TOKEN") == ("Authorization", "OLD_TOKEN")
    assert headers.parse(" X-Api-Key :env:new_key ") == ("X-Api-Key", "new_key")
    assert headers.names(["Authorization: env:A", "X-Key: env:B"]) == ["Authorization", "X-Key"]


@pytest.mark.parametrize("bad", ["Authorization: Bearer abc", "Authorization: abc", "env:X", "Bad Header: env:X",
                                 "Authorization: env:"])
def test_literal_values_rejected(bad):
    with pytest.raises(headers.HeaderError):
        headers.parse(bad)
    with pytest.raises(ValidationError):
        SourceInput(kind="api", source="http://x", headers=[bad])


def test_missing_variable_names_it_not_the_value():
    with pytest.raises(headers.HeaderError) as e:
        headers.resolve(["Authorization: env:NOPE_TOKEN"], "old", environ={})
    assert "NOPE_TOKEN" in str(e.value) and "old Authorization" in str(e.value)
    assert headers.resolve(["Authorization: env:T"], "old", environ={"T": " v "}) == {"Authorization": "v"}


class Recording(TestClient):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.seen: list[tuple[str, dict]] = []

    def request(self, method, url, *args, **kwargs):
        self.seen.append((str(url), dict(kwargs.get("headers") or {})))
        return super().request(method, url, *args, **kwargs)


def test_headers_on_spec_and_replay_and_never_saved(tmp_path, monkeypatch):
    """Review focus 4."""
    monkeypatch.setenv("OLD_TOKEN", SECRET_OLD)
    monkeypatch.setenv("NEW_KEY", SECRET_NEW)
    client = Recording(app)
    run = pipeline.run(pipeline.RunConfig(old="http://testserver/v1", new="http://testserver/v2", workers=1,
                                          retry=RetryPolicy(base=0.0),
                                          old_headers=["Authorization: env:OLD_TOKEN"],
                                          new_headers=["X-Api-Key: env:NEW_KEY"]), client)
    old_calls = [h for u, h in client.seen if "/v1/" in u]
    new_calls = [h for u, h in client.seen if "/v2/" in u]
    assert any(u.endswith("/v1/openapi.json") for u, _ in client.seen)
    assert old_calls and all(h.get("Authorization") == SECRET_OLD for h in old_calls)
    assert new_calls and all(h.get("X-Api-Key") == SECRET_NEW for h in new_calls)
    assert run.score.correct == 10
    assert run.config["old_headers"] == ["Authorization"] and run.config["new_headers"] == ["X-Api-Key"]
    text = store.save(run, tmp_path).read_text()
    assert SECRET_OLD not in text and SECRET_NEW not in text


def test_missing_variable_fails_before_any_request(monkeypatch):
    monkeypatch.delenv("NOPE_TOKEN", raising=False)
    client = Recording(app)
    with pytest.raises(headers.HeaderError):
        pipeline.run(pipeline.RunConfig(old="http://testserver/v1", new="http://testserver/v2",
                                        old_headers=["Authorization: env:NOPE_TOKEN"]), client)
    assert client.seen == []


def test_configuration_stores_reference_only(tmp_path):
    inp = RunInput(before={"kind": "api", "source": "http://a/v1", "headers": ["Authorization: env:OLD_TOKEN"]},
                   after={"kind": "api", "source": "http://a/v2"}, name="authd")
    text = save_config(inp, tmp_path).read_text()
    assert "Authorization: env:OLD_TOKEN" in text
