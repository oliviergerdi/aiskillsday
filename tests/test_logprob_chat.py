import json
import math

import httpx
import pytest

from nparity.evaluator.base import Choice, TooManyOptions
from nparity.evaluator.logprob_chat import LogprobChatBackend, codes_for, normalise_token, parse_top_logprobs
from nparity.evaluator.profiles import load_profile
from nparity.retry import RetryPolicy

E4 = json.loads(open("proto/raw/E4_1.json").read())
PROFILE = load_profile("config/profiles/flash.yaml")
Q5 = Choice(id="q", instructions="Which new endpoint is the best match?",
            criteria={k: f"desc {k}" for k in ["clients", "orders", "health", "users", "none"]})


def test_parse_e4():
    raw, unseen, off = parse_top_logprobs(E4, list("ABCDE"))
    assert raw["A"] == pytest.approx(0.998867, abs=1e-6)
    assert "D" not in raw and set(raw) == {"A", "B", "C", "E"}
    visible = sum(math.exp(lp) for lp in (-0.00113316, -7.00113297, -9.62613297, -9.75113297, -10.12613297))
    assert unseen == pytest.approx(1 - visible, abs=1e-9)      # includes the non-code token "Let"
    assert unseen < 0.05 and not off


def test_off_list():
    resp = {"choices": [{"logprobs": {"content": [{"token": "We", "logprob": -0.1,
                                                   "top_logprobs": [{"token": "We", "logprob": -0.1},
                                                                    {"token": "Let", "logprob": -2.0}]}]}}]}
    raw, _, off = parse_top_logprobs(resp, list("ABC"))
    assert raw == {} and off


def test_codes_and_tokens():
    assert codes_for(5) == list("ABCDE")
    assert codes_for(30)[0] == "01" and codes_for(30)[-1] == "30"
    assert normalise_token(" A") == normalise_token("A.") == normalise_token("A)") == "A"


def backend(handler, **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return LogprobChatBackend(PROFILE, api_key="test-key", client=client, policy=RetryPolicy(base=0.0), **kw)


def test_request_body_and_retry():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(503) if len(seen) == 1 else httpx.Response(200, json=E4)

    a = backend(handler).evaluate({"s": 1}, [Q5])["q"]
    body = json.loads(seen[-1].content)
    assert body["reasoning_effort"] == "none"
    assert (body["max_tokens"], body["top_logprobs"], body["temperature"], body["logprobs"]) == (1, 5, 0, True)
    assert body["model"].endswith("-us")
    assert seen[-1].headers["Authorization"] == "Bearer test-key"
    assert str(seen[-1].url) == "https://us.api.fireworks.ai/inference/v1/chat/completions"
    assert "A: desc clients" in body["messages"][1]["content"]
    assert a.value == "clients"
    assert a.p_winner == pytest.approx(0.998867, abs=1e-6)
    assert sum(a.probabilities.values()) == pytest.approx(1.0)
    assert a.probabilities["users"] == 0.0                        # D was never visible
    assert not a.censored and a.meta["retries"] == 1
    assert a.meta["prompt_tokens"] == E4["usage"]["prompt_tokens"]


def test_bad_request_becomes_off_list_not_crash():
    a = backend(lambda r: httpx.Response(400, json={"error": "nope"})).evaluate("s", [Q5])["q"]
    assert a.off_list and "error" in a.meta


def test_reason_second_call():
    def handler(request):
        body = json.loads(request.content)
        if body["max_tokens"] == 60:
            assert "logprobs" not in body and body["reasoning_effort"] == "none"
            return httpx.Response(200, json={"choices": [{"message": {"content": " Same resource, renamed. "}}],
                                             "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        return httpx.Response(200, json=E4)

    a = backend(handler).evaluate("s", [Q5], reasons=True)["q"]
    assert a.reason == "Same resource, renamed."
    assert a.meta["reason_call"] is True


def test_too_many_options():
    big = Choice(id="b", instructions="?", criteria={str(i): "x" for i in range(31)})
    with pytest.raises(TooManyOptions):
        backend(lambda r: httpx.Response(200, json=E4)).evaluate("s", [big])


def test_cost_estimate_while_prices_unknown():
    assert PROFILE.price.cost(159, 30, 1) == pytest.approx(0.0000734)
