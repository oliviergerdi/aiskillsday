"""LogprobChatBackend: any OpenAI-compatible chat API with top_logprobs (evaluator spec section 4).

One 1-token call per question; the answer is read from the first token's top_logprobs.
Rules from logprobs_report.md: reasoning off, top_logprobs 5, ask once with the full list,
chat completions only, raw probabilities for thresholds.
"""

from __future__ import annotations

import json
import math
import os
import string
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from nparity.evaluator.base import Answer, Choice, TooManyOptions, confidence, uniform
from nparity.evaluator.profiles import Profile, load_profile
from nparity.retry import RetryExhausted, RetryPolicy, retry_call

TEMPLATE_VERSION = "v1"
SYSTEM = ("You answer one multiple-choice question about the state below.\n"
          "Reply with only the code of the best option. No other text.")
REASON_SYSTEM = "You explain a decision in one short sentence. No preamble."
CENSORED_ABOVE = 0.05


def tls_verify() -> object:
    """Verify against the OS trust store (macOS keychain) when truststore is installed.

    Corporate TLS inspection puts its root CA in the keychain, not in certifi's bundle,
    so plain httpx fails with CERTIFICATE_VERIFY_FAILED. Verification is never disabled.
    """
    try:
        import ssl

        import truststore
    except ImportError:
        return True
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def codes_for(k: int) -> list[str]:
    if k <= 26:
        return list(string.ascii_uppercase[:k])
    return [f"{i:02d}" for i in range(1, k + 1)]


def normalise_token(tok: str) -> str:
    return tok.strip().rstrip(".:),").strip()


def parse_top_logprobs(resp: dict[str, Any], codes: list[str]) -> tuple[dict[str, float], float, bool]:
    """-> (raw p per code seen, unseen_mass, off_list). unseen_mass = 1 - sum of raw p over every visible token."""
    content = ((resp.get("choices") or [{}])[0].get("logprobs") or {}).get("content") or []
    if not content:
        return {}, 1.0, True
    first = content[0]
    tops = first.get("top_logprobs") or [first]
    visible = 0.0
    raw: dict[str, float] = {}
    for t in tops:
        p = math.exp(t["logprob"])
        visible += p
        tok = normalise_token(t["token"])
        if tok in codes:
            raw[tok] = max(raw.get(tok, 0.0), p)
    return raw, max(0.0, 1.0 - visible), not raw


def render_user(state: str | dict[str, Any], q: Choice, codes: list[str]) -> str:
    st = state if isinstance(state, str) else json.dumps(state, indent=2, ensure_ascii=False, default=str)
    options = "\n".join(f"{c}: {desc}" for c, desc in zip(codes, q.criteria.values()))
    return f"{st}\n\nQuestion: {q.instructions}\n{options}"


class LogprobChatBackend:
    template_version = TEMPLATE_VERSION

    def __init__(self, profile: Profile, api_key: str | None = None, client: httpx.Client | None = None,
                 policy: RetryPolicy = RetryPolicy(), sleep=time.sleep):
        self.profile = profile
        self.id = f"logprob_chat:{profile.key}"
        self.max_options = profile.limits.max_options
        self.api_key = api_key if api_key is not None else os.environ.get(profile.provider.api_key_env, "")
        self.client = client or httpx.Client(timeout=profile.limits.timeout_s, verify=tls_verify())
        self.policy = policy
        self.sleep = sleep
        self.url = profile.provider.base_url.rstrip("/") + profile.provider.path

    @classmethod
    def from_profile(cls, path: str | Path, **kw: Any) -> "LogprobChatBackend":
        profile = load_profile(path)
        if not kw.get("api_key") and not os.environ.get(profile.provider.api_key_env):
            raise RuntimeError(f"{profile.provider.api_key_env} is not set")
        return cls(profile, **kw)

    # -- HTTP -------------------------------------------------------------------------------------

    def _post(self, body: dict[str, Any]) -> tuple[httpx.Response, int]:
        retries = {"n": 0}

        def call() -> httpx.Response:
            r = self.client.post(self.url, json=body, headers={"Authorization": f"Bearer {self.api_key}"})
            r.raise_for_status()      # retryable statuses retry; any other 4xx/5xx is a bug and surfaces
            return r

        def count(*_: Any) -> None:
            retries["n"] += 1

        r = retry_call(call, self.policy, sleep=self.sleep, on_retry=count)
        return r, retries["n"]

    def _meta(self, r: httpx.Response, started: float, retries: int, **extra: Any) -> dict[str, Any]:
        usage = r.json().get("usage") or {}
        prompt = int(usage.get("prompt_tokens") or 0)
        cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens")
                     or r.headers.get("fireworks-cached-prompt-tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        return {"backend": self.id, "latency_s": round(time.perf_counter() - started, 3),
                "prompt_tokens": prompt, "cached_tokens": cached, "completion_tokens": completion,
                "cost_usd": self.profile.price.cost(prompt, cached, completion), "retries": retries, **extra}

    # -- one question -------------------------------------------------------------------------------

    def ask(self, state: str | dict[str, Any], q: Choice, reasons: bool) -> Answer:
        keys = list(q.criteria)
        if len(keys) > self.max_options:
            raise TooManyOptions(f"{q.id}: {len(keys)} options > {self.max_options}")
        codes = codes_for(len(keys))
        user = render_user(state, q, codes)
        req = self.profile.request
        body = {"model": self.profile.provider.model,
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                "temperature": req.temperature, "max_tokens": req.max_tokens, "logprobs": req.logprobs,
                "top_logprobs": req.top_logprobs, **req.extra}
        started = time.perf_counter()
        try:
            r, retries = self._post(body)
        except (RetryExhausted, httpx.HTTPError) as e:
            return uniform(keys, reason=f"LLM error: {e}" if reasons else None,
                           meta={"backend": self.id, "error": str(e), "cost_usd": 0.0})
        meta = self._meta(r, started, retries)
        raw, unseen, off_list = parse_top_logprobs(r.json(), codes)
        if off_list:
            return uniform(keys, meta=meta)
        by_key = {keys[codes.index(c)]: p for c, p in raw.items()}
        total = sum(by_key.values())
        probs = {k: by_key.get(k, 0.0) / total for k in keys}       # display only
        winner = max(by_key, key=by_key.get)
        answer = Answer(value=winner, probabilities=probs, p_winner=by_key[winner], confidence=confidence(probs),
                        unseen_mass=unseen, censored=unseen > CENSORED_ABOVE, meta=meta)
        if reasons:
            answer.reason = self._reason(user, codes[keys.index(winner)], q.criteria[winner], answer)
        return answer

    def _reason(self, user: str, code: str, desc: str, answer: Answer) -> str | None:
        body = {"model": self.profile.provider.model,
                "messages": [{"role": "system", "content": REASON_SYSTEM},
                             {"role": "user", "content": f"{user}\n\nThe best option is {code} ({desc}). "
                                                         "In one sentence, why?"}],
                "temperature": 0, "max_tokens": self.profile.reason.max_tokens, **self.profile.request.extra}
        started = time.perf_counter()
        try:
            r, retries = self._post(body)
        except (RetryExhausted, httpx.HTTPError):
            return None
        m = self._meta(r, started, retries)
        for k in ("prompt_tokens", "cached_tokens", "completion_tokens", "cost_usd", "retries"):
            answer.meta[k] = answer.meta.get(k, 0) + m[k]
        answer.meta["reason_call"] = True
        text = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return text.strip() or None

    # -- Backend --------------------------------------------------------------------------------------

    def evaluate(self, state: str | dict[str, Any], questions: list[Choice],
                 reasons: bool = False) -> dict[str, Answer]:
        if len(questions) == 1:
            return {questions[0].id: self.ask(state, questions[0], reasons)}
        with ThreadPoolExecutor(max_workers=self.profile.limits.concurrency) as pool:
            answers = list(pool.map(lambda q: self.ask(state, q, reasons), questions))
        return {q.id: a for q, a in zip(questions, answers)}
