#!/usr/bin/env python3
"""logprobs_test.py -- probe logprob behaviour of DeepSeek Flash on Fireworks AI.

Fireworks exposes an OpenAI-compatible API, so this uses the `openai` SDK with a
custom base_url. Auth is read from the FIREWORKS_API_KEY environment variable;
the key is never hardcoded, printed, or written to disk by this script.

    export FIREWORKS_API_KEY=...      # never committed
    python logprobs_test.py                 # run all experiments
    python logprobs_test.py --exp E1 E2     # run a subset
    python logprobs_test.py --model accounts/fireworks/routers/deepseek-v4p1-flash-1017-us

Outputs:
    raw/<EXP>_<n>.json    raw JSON response per recorded call
    results.json          machine-readable summary of every experiment
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from openai import BadRequestError, OpenAI

BASE_URL = "https://us.api.fireworks.ai/inference/v1"

# Model id resolution (see E0 in the report):
#   GET /models lists the *deployment* ids, e.g.
#     accounts/fireworks/models/deepseek-v4p1-flash-1017      -> HTTP 403 (region)
#     accounts/fireworks/routers/deepseek-v4p1-flash-1017-spot -> HTTP 403 (region)
#   The account is pinned to US data residency, so only `-us` routers work:
#     accounts/fireworks/routers/deepseek-v4p1-flash-1017-us   -> HTTP 200  <-- newest
#     accounts/fireworks/routers/deepseek-v4p1-flash-us        -> HTTP 200  (older)
#     accounts/fireworks/routers/deepseek-v4p1-flash-1017-ultrafast -> HTTP 200 (not US-pinned)
#   The router resolves server-side to accounts/fireworks/models/deepseek-v4p1-flash-1017
MODEL = "accounts/fireworks/routers/deepseek-v4p1-flash-1017-us"

RAW = Path(__file__).parent / "raw"
RAW.mkdir(exist_ok=True)

SYSTEM_CHOICE = (
    "You map API endpoints between an old and a new version. "
    "Answer with only the letter of the best match. No other text."
)

USER_CHOICE = """Old endpoint: GET /customers/{id}
Returns: { "id": string, "fullName": string, "email": string, "legacyCode": string, "currency": string }

Which new endpoint is the same operation?
A: GET /v2/clients/{clientId}  returns { id, name, email, currency }
B: GET /v2/orders/{orderId}  returns { id, total, items, createdAt }
C: POST /v2/clients  creates a client
D: GET /v2/clients  lists clients with pagination
E: None of these"""


# --------------------------------------------------------------------------- #
# plumbing
# --------------------------------------------------------------------------- #
def client() -> OpenAI:
    key = os.environ.get("FIREWORKS_API_KEY")
    if not key:
        sys.exit("FIREWORKS_API_KEY is not set. Export it first (never hardcode it).")
    return OpenAI(base_url=BASE_URL, api_key=key, timeout=180.0, max_retries=2)


CLIENT = None
COUNTER: dict[str, int] = {}


def _dump(exp: str, resp: dict[str, Any] | None, err: str | None) -> str | None:
    """Persist the raw response (or the raw error) for this call."""
    COUNTER[exp] = COUNTER.get(exp, 0) + 1
    path = RAW / f"{exp}_{COUNTER[exp]}.json"
    path.write_text(json.dumps(resp if resp is not None else {"error": err}, indent=2))
    return path.name


def chat(exp: str, *, record: bool = True, **kwargs: Any) -> dict[str, Any]:
    """One chat completion. Never raises; returns a result envelope."""
    body = {"model": MODEL, **kwargs}
    t0 = time.perf_counter()
    try:
        resp = CLIENT.chat.completions.create(**body)
        latency = time.perf_counter() - t0
        d = resp.model_dump(mode="json")
        if record:
            _dump(exp, d, None)
        return {"ok": True, "resp": d, "error": None, "latency": latency, "request": body}
    except Exception as e:  # noqa: BLE001 - we want the error text, whatever it is
        latency = time.perf_counter() - t0
        detail = {
            "type": type(e).__name__,
            "status": getattr(e, "status_code", None),
            "message": getattr(e, "message", None) or str(e),
            "code": getattr(e, "code", None),
            "param": getattr(e, "param", None),
            "body": getattr(e, "body", None),
        }
        if record:
            _dump(exp, None, detail)
        return {"ok": False, "resp": None, "error": detail, "latency": latency, "request": body}


def flat_err(r: dict[str, Any]) -> str:
    e = r["error"]
    return f"HTTP {e['status']} {e['type']}: {e['message']}"


def lp_content(r: dict[str, Any]) -> list[dict[str, Any]]:
    """choice.logprobs.content -- [] if the provider returned nothing there."""
    ch = r["resp"]["choices"][0]
    lps = ch.get("logprobs") or {}
    return lps.get("content") or []


def toks_in(top: list[dict[str, Any]]) -> dict[str, float]:
    return {t["token"]: t["logprob"] for t in top}


def probs_over(top: list[dict[str, Any]] | dict[str, float], codes: list[str]) -> dict[str, float]:
    """Softmax restricted to `codes`, using each code's best-matching token.

    Preference order per code: the bare code, then ' ' + code (leading space),
    then code + '.' -- whichever actually appears in top_logprobs.
    Codes absent from top_logprobs are reported as None (below the cutoff floor).
    """
    import math

    table = top if isinstance(top, dict) else toks_in(top)
    got: dict[str, float] = {}
    for code in codes:
        for variant in (code, f" {code}", f"{code}.", f" {code}.", code.lower(),
                        f" {code.lower()}"):
            if variant in table:
                got[code] = table[variant]
                break
    if not got:
        return {c: None for c in codes}
    m = max(got.values())
    exps = {c: math.exp(v - m) for c, v in got.items()}
    z = sum(exps.values())
    return {c: (exps[c] / z if c in exps else None) for c in codes}


RESULTS: dict[str, Any] = {}


# --------------------------------------------------------------------------- #
# E1 -- does logprobs work at all
# --------------------------------------------------------------------------- #
def e1() -> dict[str, Any]:
    r = chat(
        "E1",
        messages=[
            {"role": "system", "content": SYSTEM_CHOICE},
            {"role": "user", "content": USER_CHOICE},
        ],
        temperature=0,
        max_tokens=5,
        logprobs=True,
        top_logprobs=5,
    )
    out: dict[str, Any] = {"model": MODEL, "ok": r["ok"], "latency": r["latency"]}
    if not r["ok"]:
        out["error"] = flat_err(r)
        return out
    d = r["resp"]
    ch = d["choices"][0]
    lps = ch.get("logprobs")
    out["choice_keys"] = sorted(ch.keys())
    out["logprobs_present"] = lps is not None
    out["logprobs_keys"] = sorted(lps.keys()) if isinstance(lps, dict) else None
    content = (lps or {}).get("content") or []
    out["n_content_entries"] = len(content)
    out["content_entry_keys"] = sorted(content[0].keys()) if content else None
    out["top_logprobs_entry_keys"] = (
        sorted(content[0]["top_logprobs"][0].keys())
        if content and content[0].get("top_logprobs") else None
    )
    out["first_token"] = content[0]["token"] if content else None
    out["first_token_logprob"] = content[0]["logprob"] if content else None
    out["first_top_logprobs"] = toks_in(content[0]["top_logprobs"]) if content else None
    out["finish_reason"] = ch.get("finish_reason")
    out["message_keys"] = sorted(ch["message"].keys())
    out["content_text"] = ch["message"].get("content")
    return out


# --------------------------------------------------------------------------- #
# E2 -- max top_logprobs
# --------------------------------------------------------------------------- #
def e2() -> dict[str, Any]:
    rows = []
    for n in (5, 10, 20, 50, 100):
        r = chat(
            "E2",
            messages=[
                {"role": "system", "content": SYSTEM_CHOICE},
                {"role": "user", "content": USER_CHOICE},
            ],
            temperature=0,
            max_tokens=1,
            logprobs=True,
            top_logprobs=n,
        )
        row: dict[str, Any] = {"requested": n, "ok": r["ok"]}
        if r["ok"]:
            c = lp_content(r)
            row["accepted"] = True
            row["returned"] = len(c[0]["top_logprobs"]) if c else 0
        else:
            row["accepted"] = False
            row["error"] = flat_err(r)
            row["status"] = r["error"]["status"]
        rows.append(row)
    accepted = [r["requested"] for r in rows if r["accepted"]]
    return {
        "rows": rows,
        "max_accepted": max(accepted) if accepted else None,
        "rejections": [r for r in rows if not r["accepted"]],
    }


# --------------------------------------------------------------------------- #
# E0 -- model id resolution
# --------------------------------------------------------------------------- #
def e0() -> dict[str, Any]:
    """Which DeepSeek Flash ids exist and which ones this account may call."""
    candidates = [
        "accounts/fireworks/models/deepseek-v4p1-flash-1017",
        "accounts/fireworks/models/deepseek-v4p1-flash",
        "accounts/fireworks/routers/deepseek-v4p1-flash-1017-us",
        "accounts/fireworks/routers/deepseek-v4p1-flash-us",
        "accounts/fireworks/routers/deepseek-v4p1-flash-1017-ultrafast",
        "accounts/fireworks/routers/deepseek-v4p1-flash-1017-spot",
        "accounts/fireworks/routers/deepseek-v4p1-flash-spot",
        "accounts/fireworks/routers/spot-deepseek-v4-flash",
    ]
    rows = []
    global MODEL
    keep = MODEL
    for m in candidates:
        MODEL = m
        r = chat(
            "E0",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
            temperature=0,
        )
        rows.append(
            {
                "id": m,
                "http": 200 if r["ok"] else r["error"]["status"],
                "error": None if r["ok"] else r["error"]["message"],
                "resolved_model": (r["resp"] or {}).get("model"),
            }
        )
    MODEL = keep
    usable = [r["id"] for r in rows if r["http"] == 200]
    return {"default_model": keep, "rows": rows, "usable": usable,
            "newest_usable": [u for u in usable if "1017" in u][:1],
            "region_blocked": [r["id"] for r in rows if r["http"] == 403]}


# --------------------------------------------------------------------------- #
# E3 -- reasoning / thinking behaviour and how to switch it off
# --------------------------------------------------------------------------- #
E3_ATTEMPTS = [
    ("baseline (no param)", {}),
    ("reasoning_effort=none", {"reasoning_effort": "none"}),
    ("reasoning_effort=minimal", {"reasoning_effort": "minimal"}),
    ("reasoning_effort=low", {"reasoning_effort": "low"}),
    ("extra_body thinking.type=disabled", {"extra_body": {"thinking": {"type": "disabled"}}}),
    ("extra_body chat_template_kwargs.thinking=false",
     {"extra_body": {"chat_template_kwargs": {"thinking": False}}}),
    ("extra_body reasoning.enabled=false", {"extra_body": {"reasoning": {"enabled": False}}}),
    ("extra_body disable_thinking=true", {"extra_body": {"disable_thinking": True}}),
    ("system prompt: answer immediately",
     {"messages_override": "no_think"}),
]


def _e3_messages(kind: str | None):
    if kind == "no_think":
        return [
            {"role": "system", "content": SYSTEM_CHOICE + " Do not think step by step. Output the letter immediately."},
            {"role": "user", "content": USER_CHOICE},
        ]
    return [
        {"role": "system", "content": SYSTEM_CHOICE},
        {"role": "user", "content": USER_CHOICE},
    ]


def e3() -> dict[str, Any]:
    rows = []
    for label, kw in E3_ATTEMPTS:
        kw = dict(kw)
        msgs = _e3_messages(kw.pop("messages_override", None))
        r = chat("E3", messages=msgs, temperature=0, max_tokens=16,
                 logprobs=True, top_logprobs=5, **kw)
        row: dict[str, Any] = {"variant": label, "ok": r["ok"]}
        if not r["ok"]:
            row["error"] = flat_err(r)
            rows.append(row)
            continue
        ch = r["resp"]["choices"][0]
        msg = ch["message"]
        rc = msg.get("reasoning_content") or ""
        content = msg.get("content") or ""
        lps = lp_content(r)
        row.update(
            reasoning_chars=len(rc),
            reasoning_head=rc[:80],
            content=content,
            has_think_tag="<think" in content or "</think>" in content,
            finish_reason=ch.get("finish_reason"),
            reasoning_tokens=(r["resp"].get("usage") or {}).get("completion_tokens_details", {}).get("reasoning_tokens"),
            first_tokens=[e["token"] for e in lps[:4]],
            logprob_tokens_are_reasoning=bool(lps) and content == "" and rc != "",
        )
        rows.append(row)

    # with max_tokens=1: is the single returned token the answer, and is it in top_logprobs?
    r1 = chat("E3", messages=_e3_messages(None), temperature=0, max_tokens=1,
              logprobs=True, top_logprobs=5)
    mt1: dict[str, Any] = {"ok": r1["ok"]}
    if r1["ok"]:
        lps = lp_content(r1)
        ch = r1["resp"]["choices"][0]
        mt1.update(
            content=ch["message"].get("content"),
            reasoning=(ch["message"].get("reasoning_content") or "")[:60],
            first_token=lps[0]["token"] if lps else None,
            first_top=[t["token"] for t in (lps[0]["top_logprobs"] if lps else [])],
            answer_token_in_top=bool(lps) and any(
                t["token"].strip() in {"A", "B", "C", "D", "E"} for t in lps[0]["top_logprobs"]),
        )
    else:
        mt1["error"] = flat_err(r1)

    disabled = [r["variant"] for r in rows
                if r.get("ok") and r.get("reasoning_chars") == 0 and (r.get("content") or "").strip()]
    return {"rows": rows, "max_tokens_1": mt1, "variants_without_reasoning": disabled}


# --------------------------------------------------------------------------- #
# shared prompt builders
# --------------------------------------------------------------------------- #
OLD_ENDPOINT = (
    'Old endpoint: GET /customers/{id}\n'
    'Returns: { "id": string, "fullName": string, "email": string, '
    '"legacyCode": string, "currency": string }'
)

# canonical option text, keyed by the *semantic* option (A..E in the brief's order)
OPTION_TEXT = {
    "clients_by_id": "GET /v2/clients/{clientId}  returns { id, name, email, currency }",  # correct
    "orders_by_id": "GET /v2/orders/{orderId}  returns { id, total, items, createdAt }",
    "create_client": "POST /v2/clients  creates a client",
    "list_clients": "GET /v2/clients  lists clients with pagination",
    "none": "None of these",
}
CORRECT_SEMANTIC = "clients_by_id"


def build_choice_user(order: list[str]) -> str:
    """order = list of 5 semantic option keys, assigned letters A..E in that order."""
    letters = "ABCDE"
    lines = "\n".join(f"{letters[i]}: {OPTION_TEXT[k]}" for i, k in enumerate(order))
    return f"{OLD_ENDPOINT}\n\nWhich new endpoint is the same operation?\n{lines}"


# the brief's exact prompt (verbatim), plus the same text produced by build_choice_user
BRIEF_ORDER = ["clients_by_id", "orders_by_id", "create_client", "list_clients", "none"]

BASE = {"temperature": 0, "max_tokens": 1, "logprobs": True, "top_logprobs": 5,
        "reasoning_effort": "none"}


# --------------------------------------------------------------------------- #
# E4 -- the core test: distribution over A..E
# --------------------------------------------------------------------------- #
def e4() -> dict[str, Any]:
    r = chat("E4", messages=[{"role": "system", "content": SYSTEM_CHOICE},
                              {"role": "user", "content": USER_CHOICE}], **BASE)
    out: dict[str, Any] = {"request": {k: v for k, v in BASE.items()}, "ok": r["ok"]}
    if not r["ok"]:
        out["error"] = flat_err(r)
        return out
    lps = lp_content(r)
    top = lps[0]["top_logprobs"]
    codes = list("ABCDE")
    out.update(
        first_token=lps[0]["token"],
        is_exactly_A=lps[0]["token"] == "A",
        first_token_logprob=lps[0]["logprob"],
        full_text="".join(e["token"] for e in lps),
        message_content=r["resp"]["choices"][0]["message"].get("content"),
        top_logprobs=[{"token": t["token"], "logprob": t["logprob"],
                       "prob": __import__("math").exp(t["logprob"])} for t in top],
        codes_present={c: next((v for v in (c, f" {c}", f"{c}.", f" {c}.") if v in toks_in(top)), None)
                       for c in codes},
        distribution=probs_over(top, codes),
        usage=r["resp"].get("usage"),
    )
    return out


# --------------------------------------------------------------------------- #
# E5 -- yes/no
# --------------------------------------------------------------------------- #
YESNO_SYSTEM = "Answer with only Y or N. No other text."
YESVAR = ["Y", " Y", "Yes", " Yes", "YES", " YES"]
NOVAR = ["N", " N", "No", " No", "NO", " NO"]


def yesno(exp: str, candidate: str) -> dict[str, Any]:
    user = (f'{OLD_ENDPOINT}\n\nIs `{candidate}` the same operation? Answer Y or N.')
    r = chat(exp, messages=[{"role": "system", "content": YESNO_SYSTEM},
                            {"role": "user", "content": user}], **BASE)
    out: dict[str, Any] = {"candidate": candidate, "ok": r["ok"]}
    if not r["ok"]:
        out["error"] = flat_err(r)
        return out
    import math
    lps = lp_content(r)
    top = toks_in(lps[0]["top_logprobs"])
    out.update(
        first_token=lps[0]["token"],
        top_logprobs={k: {"logprob": v, "prob": math.exp(v)} for k, v in top.items()},
        p_y_variants={v: (math.exp(top[v]) if v in top else None) for v in YESVAR},
        p_n_variants={v: (math.exp(top[v]) if v in top else None) for v in NOVAR},
        p_y=sum(math.exp(top[v]) for v in YESVAR if v in top),
        p_n=sum(math.exp(top[v]) for v in NOVAR if v in top),
    )
    out["p_y_normalised"] = (out["p_y"] / (out["p_y"] + out["p_n"])) if (out["p_y"] + out["p_n"]) else None
    return out


def e5() -> dict[str, Any]:
    return {
        "correct_candidate": yesno("E5", "GET /v2/clients/{clientId}"),
        "wrong_candidate": yesno("E5", "GET /v2/orders/{orderId}"),
    }


# --------------------------------------------------------------------------- #
# E6 -- position bias
# --------------------------------------------------------------------------- #
E6_ORDERS = [
    ["clients_by_id", "orders_by_id", "create_client", "list_clients", "none"],
    ["orders_by_id", "create_client", "clients_by_id", "none", "list_clients"],
    ["none", "list_clients", "orders_by_id", "clients_by_id", "create_client"],
]


def e6() -> dict[str, Any]:
    rows = []
    for i, order in enumerate(E6_ORDERS, start=1):
        user = build_choice_user(order)
        r = chat("E6", messages=[{"role": "system", "content": SYSTEM_CHOICE},
                                  {"role": "user", "content": user}], **BASE)
        correct_letter = "ABCDE"[order.index(CORRECT_SEMANTIC)]
        row: dict[str, Any] = {"order": i, "correct_letter": correct_letter,
                               "letters": dict(zip("ABCDE", order)), "ok": r["ok"]}
        if not r["ok"]:
            row["error"] = flat_err(r)
            rows.append(row)
            continue
        lps = lp_content(r)
        top = lps[0]["top_logprobs"]
        dist = probs_over(top, list("ABCDE"))
        row.update(first_token=lps[0]["token"], distribution=dist,
                   p_correct=dist.get(correct_letter), p_A=dist.get("A"),
                   correct_is_argmax=(max(dist, key=lambda k: dist[k] or -1) == correct_letter)
                   if any(v is not None for v in dist.values()) else None,
                   top_logprobs=[{"token": t["token"], "logprob": t["logprob"]} for t in top])
        rows.append(row)
    return {"rows": rows,
            "p_correct_each_order": [r.get("p_correct") for r in rows]}


# --------------------------------------------------------------------------- #
# E7 -- determinism
# --------------------------------------------------------------------------- #
def e7(n: int = 5) -> dict[str, Any]:
    runs = []
    for _ in range(n):
        r = chat("E7", messages=[{"role": "system", "content": SYSTEM_CHOICE},
                                  {"role": "user", "content": USER_CHOICE}], **BASE)
        if not r["ok"]:
            runs.append({"ok": False, "error": flat_err(r)})
            continue
        lps = lp_content(r)
        dist = probs_over(lps[0]["top_logprobs"], list("ABCDE"))
        runs.append({"ok": True, "first_token": lps[0]["token"], "distribution": dist,
                     "raw_top": {t["token"]: t["logprob"] for t in lps[0]["top_logprobs"]},
                     "latency": r["latency"], "completion_tokens":
                     (r["resp"].get("usage") or {}).get("completion_tokens")})
    dists = [r["distribution"] for r in runs if r["ok"]]
    spread = {}
    for code in "ABCDE":
        vals = [d.get(code) for d in dists if d.get(code) is not None]
        spread[code] = {"min": min(vals), "max": max(vals),
                        "range": max(vals) - min(vals), "n": len(vals)} if vals else None
    identical = len({json.dumps(d, sort_keys=True) for d in dists}) == 1
    return {"runs": runs, "identical": identical, "spread": spread,
            "n_runs": len(dists),
            "first_token_counts": {t: sum(1 for r in runs if r.get("first_token") == t)
                                   for t in {r.get("first_token") for r in runs if r["ok"]}}}


# --------------------------------------------------------------------------- #
# E8 -- 30 options
# --------------------------------------------------------------------------- #
E8_DISTRACTORS = [
    "GET /v2/clients/{clientId}/orders  returns a list of orders",
    "PATCH /v2/clients/{clientId}  updates a client",
    "DELETE /v2/clients/{clientId}  deletes a client",
    "GET /v2/clients/{clientId}/balance  returns the account balance",
    "GET /v1/clients/{clientId}  legacy client lookup",
    "GET /v2/customers/{customerId}  returns { id, fullName, email }",
    "GET /v2/accounts/{accountId}  returns { id, name, currency }",
    "GET /v2/contacts/{contactId}  returns { id, name, email }",
    "POST /v2/orders  creates an order",
    "GET /v2/orders  lists orders with pagination",
    "GET /v2/invoices/{invoiceId}  returns { id, total, currency }",
    "GET /v2/products/{productId}  returns { id, name, price }",
    "GET /v2/users/{userId}  returns { id, email, role }",
    "GET /v2/clients/search  searches clients by name",
    "POST /v2/clients/{clientId}/archive  archives a client",
    "GET /v2/clients/{clientId}/history  returns audit history",
    "GET /v2/vendors/{vendorId}  returns { id, name, currency }",
    "GET /v2/leads/{leadId}  returns { id, name, email }",
    "PUT /v2/clients/{clientId}  replaces a client",
    "GET /v2/clients/{clientId}/currency  returns the currency code",
    "GET /v2/customers/{id}/orders  lists a customer's orders",
    "GET /v2/payments/{paymentId}  returns { id, amount, currency }",
    "GET /v2/plans/{planId}  returns { id, name, price }",
    "GET /v2/teams/{teamId}  returns { id, name, members }",
    "HEAD /v2/clients/{clientId}  checks existence",
    "GET /v2/clients/{clientId}/metadata  returns custom metadata",
    "GET /v2/entities/{entityId}  returns { id, fullName, email, currency }",
    "GET /v2/directory/{directoryId}  returns { id, name, email }",
    "GET /v2/clients/{clientId}?include=legacyCode  same endpoint, extra field",
]


def e8() -> dict[str, Any]:
    correct = OPTION_TEXT["clients_by_id"]
    opts = [(correct, True)] + [(d, False) for d in E8_DISTRACTORS]
    # shuffle deterministically so the correct one is not always first
    order_idx = [7] + [i for i in range(len(opts)) if i != 7]
    opts = [opts[i] for i in order_idx]
    lines, codes, correct_code = [], [], None
    for i, (text, is_correct) in enumerate(opts, start=1):
        code = f"{i:02d}"
        codes.append(code)
        if is_correct:
            correct_code = code
        lines.append(f"{code}: {text}")
    user = (f"{OLD_ENDPOINT}\n\nWhich new endpoint is the same operation?\n" + "\n".join(lines))
    r = chat("E8", messages=[{"role": "system", "content": SYSTEM_CHOICE},
                              {"role": "user", "content": user}], **BASE)
    out: dict[str, Any] = {"n_options": len(opts), "correct_code": correct_code,
                           "prompt_tokens": None, "ok": r["ok"]}
    if not r["ok"]:
        out["error"] = flat_err(r)
        return out
    import math
    lps = lp_content(r)
    top = lps[0]["top_logprobs"]
    dist = probs_over(top, codes)
    present = [c for c in codes if dist.get(c) is not None]
    out.update(
        prompt_tokens=(r["resp"].get("usage") or {}).get("prompt_tokens"),
        first_token=lps[0]["token"],
        top_logprobs=[{"token": t["token"], "logprob": t["logprob"],
                       "prob": math.exp(t["logprob"])} for t in top],
        codes_seen_in_top_logprobs=present,
        n_codes_seen=len(present),
        p_correct=dist.get(correct_code),
        correct_wins=(dist.get(correct_code) is not None and
                      dist[correct_code] == max(v for v in dist.values() if v is not None)),
    )
    return out


# --------------------------------------------------------------------------- #
# E9 -- JSON mode with logprobs
# --------------------------------------------------------------------------- #
JSON_SCHEMA = {
    "type": "object",
    "properties": {"label": {"type": "string", "enum": list("ABCDE")},
                   "reason": {"type": "string"}},
    "required": ["label", "reason"],
    "additionalProperties": False,
}


def _json_attempt(exp_note: str, response_format: dict[str, Any]) -> dict[str, Any]:
    r = chat("E9", messages=[{"role": "system", "content": SYSTEM_CHOICE + ' Reply as JSON: {"label":"<letter>","reason":"<short>"}'},
                              {"role": "user", "content": USER_CHOICE}],
             temperature=0, max_tokens=60, logprobs=True, top_logprobs=5,
             reasoning_effort="none", response_format=response_format)
    out: dict[str, Any] = {"variant": exp_note, "ok": r["ok"]}
    if not r["ok"]:
        out["error"] = flat_err(r)
        return out
    lps = lp_content(r)
    text = "".join(e["token"] for e in lps)
    out["content"] = r["resp"]["choices"][0]["message"].get("content")
    out["tokens_with_logprobs"] = len(lps)
    # locate the label value token inside the JSON
    idx = None
    if '"label"' in text:
        after = text.split('"label"', 1)[1]
        # skip  optional spaces, ':' , quotes
        pos = text.index('"label"') + len('"label"')
        while pos < len(text) and text[pos] in ' \t:':
            pos += 1
        if pos < len(text) and text[pos] == '"':
            pos += 1
        # map char offset -> token index by accumulating token lengths
        acc = 0
        for i, e in enumerate(lps):
            acc += len(e["token"])
            if acc > pos:
                idx = i
                break
    out["label_token_index"] = idx
    if idx is not None:
        e = lps[idx]
        out["label_token"] = e["token"]
        out["label_logprob"] = e["logprob"]
        out["label_top_logprobs"] = {t["token"]: t["logprob"] for t in e["top_logprobs"]}
        out["label_distribution"] = probs_over(e["top_logprobs"], list("ABCDE"))
    return out


def e9() -> dict[str, Any]:
    return {
        "json_object": _json_attempt("response_format=json_object", {"type": "json_object"}),
        "json_schema": _json_attempt("response_format=json_schema(strict)", {
            "type": "json_schema",
            "json_schema": {"name": "endpoint_match", "schema": JSON_SCHEMA, "strict": True},
        }),
    }


# --------------------------------------------------------------------------- #
# E10 -- plain /completions
# --------------------------------------------------------------------------- #
def e10() -> dict[str, Any]:
    out: dict[str, Any] = {}
    prompt = (f"{OLD_ENDPOINT}\n\nWhich new endpoint is the same operation?\n"
              + "\n".join(f"{chr(65+i)}: {OPTION_TEXT[k]}" for i, k in enumerate(BRIEF_ORDER))
              + "\n\nAnswer:")
    for label, kw in (
        ("logprobs+echo", {"logprobs": 5, "echo": True, "max_tokens": 1}),
        ("logprobs, no echo", {"logprobs": 5, "echo": False, "max_tokens": 1}),
    ):
        try:
            t0 = time.perf_counter()
            # /completions does not type `reasoning_effort`, so it must go via extra_body
            resp = CLIENT.completions.create(model=MODEL, prompt=prompt, temperature=0,
                                             extra_body={"reasoning_effort": "none"}, **kw)
            d = resp.model_dump(mode="json")
            _dump("E10", d, None)
            ch = d["choices"][0]
            lps = ch.get("logprobs") or {}
            out[label] = {
                "ok": True, "latency": time.perf_counter() - t0,
                "completion_text": ch.get("text"),
                "logprobs_keys": sorted(lps.keys()),
                "n_token_lp": len(lps.get("tokens") or []),
                "n_prompt_lp": len((lps.get("token_logprobs") or [])),
                "n_top_lp": len(lps.get("top_logprobs") or []),
                "first_tokens": (lps.get("tokens") or [])[:5],
                "last_tokens": (lps.get("tokens") or [])[-5:],
                "sample_top": (lps.get("top_logprobs") or [None])[-1],
                "prompt_tokens": (d.get("usage") or {}).get("prompt_tokens"),
                "raw_prompt_echo_chars": len(ch.get("text") or ""),
            }
        except Exception as e:  # noqa: BLE001
            _dump("E10", None, {"type": type(e).__name__, "status": getattr(e, "status_code", None),
                                "message": getattr(e, "message", None) or str(e)})
            out[label] = {"ok": False, "status": getattr(e, "status_code", None),
                          "error": f"HTTP {getattr(e, 'status_code', '?')} {type(e).__name__}: "
                                   f"{getattr(e, 'message', None) or str(e)}"}
    return out


# --------------------------------------------------------------------------- #
# E11 -- caching, latency, cost, rate-limit headers
# --------------------------------------------------------------------------- #
def e11(n: int = 10) -> dict[str, Any]:
    lat, cached, ptok, ctok, headers_seen = [], [], [], [], None
    runs = []
    for i in range(n):
        t0 = time.perf_counter()
        raw = CLIENT.chat.completions.with_raw_response.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM_CHOICE},
                      {"role": "user", "content": USER_CHOICE}],
            **BASE,
        )
        elapsed = time.perf_counter() - t0
        d = raw.parse().model_dump(mode="json")
        if i == 0:
            headers_seen = {k: v for k, v in raw.headers.items()
                            if any(s in k.lower() for s in ("rate", "limit", "retry", "request",
                                                            "cache", "remaining", "x-"))}
            _dump("E11", d, None)
        u = d.get("usage") or {}
        ptd = u.get("prompt_tokens_details") or {}
        lat.append(elapsed)
        cached.append(ptd.get("cached_tokens"))
        ptok.append(u.get("prompt_tokens"))
        ctok.append(u.get("completion_tokens"))
        runs.append({"i": i, "latency": elapsed, "prompt_tokens": u.get("prompt_tokens"),
                     "completion_tokens": u.get("completion_tokens"),
                     "cached_tokens": ptd.get("cached_tokens"),
                     "id": d.get("id"), "system_fingerprint": d.get("system_fingerprint")})
    price_in, price_out, price_cached = 0.45, 1.80, 0.009  # USD per 1M tokens, pi model config
    med_ptok = statistics.median([p for p in ptok if p])
    med_ctok = statistics.median([c for c in ctok if c is not None])
    all_cached = [c for c in cached if isinstance(c, int)]
    return {
        "n_calls": n,
        "latency_s": {"median": statistics.median(lat),
                      "min": min(lat), "max": max(lat),
                      "all": lat},
        "prompt_tokens_per_call": med_ptok,
        "completion_tokens_per_call": med_ctok,
        "cached_tokens_per_call": all_cached,
        "any_cached": any(c > 0 for c in all_cached),
        "cost_usd_per_call": ((med_ptok or 0) * price_in + (med_ctok or 0) * price_out) / 1e6,
        "price_usd_per_mtok": {"input": price_in, "output": price_out, "cached_input": price_cached,
                               "source": "pi model config (models.json); Fireworks pricing page not queried"},
        "rate_limit_headers": headers_seen,
        "runs": runs,
    }


# --------------------------------------------------------------------------- #
# E12 -- 10 options, and whether a two-stage shortlist recovers the full distribution
# --------------------------------------------------------------------------- #
E12_OPTIONS = [
    ("correct", OPTION_TEXT["clients_by_id"]),
    ("orders_by_id", OPTION_TEXT["orders_by_id"]),
    ("create_client", OPTION_TEXT["create_client"]),
    ("list_clients", OPTION_TEXT["list_clients"]),
    ("none", OPTION_TEXT["none"]),
    ("patch_client", "PATCH /v2/clients/{clientId}  updates a client"),
    ("client_orders", "GET /v2/clients/{clientId}/orders  returns a list of orders"),
    ("contacts", "GET /v2/contacts/{contactId}  returns { id, name, email }"),
    ("accounts", "GET /v2/accounts/{accountId}  returns { id, name, currency }"),
    ("customers_v2", "GET /v2/customers/{customerId}  returns { id, fullName, email }"),
]
# three deterministic orders: correct option in slot 1, slot 5, slot 10
E12_ORDERS = [
    ["correct"] + [k for k, _ in E12_OPTIONS[1:]],
    [k for k, _ in E12_OPTIONS[1:4]] + ["correct"] + [k for k, _ in E12_OPTIONS[4:]],
    [k for k, _ in E12_OPTIONS[1:]] + ["correct"],
]
E12_TEXT = dict(E12_OPTIONS)
LETTERS10 = "ABCDEFGHIJ"

# Same 10-option shape, but no near-duplicate distractor: `customers_v2` is dropped
# because "GET /v2/customers/{customerId} ... fullName" is a literal near-copy of the
# old endpoint and makes the question genuinely ambiguous rather than 10-way.
E14_OPTIONS = [
    ("correct", OPTION_TEXT["clients_by_id"]),
    ("orders_by_id", OPTION_TEXT["orders_by_id"]),
    ("create_client", OPTION_TEXT["create_client"]),
    ("list_clients", OPTION_TEXT["list_clients"]),
    ("none", OPTION_TEXT["none"]),
    ("patch_client", "PATCH /v2/clients/{clientId}  updates a client"),
    ("client_orders", "GET /v2/clients/{clientId}/orders  returns a list of orders"),
    ("contacts", "GET /v2/contacts/{contactId}  returns { id, name, email }"),
    ("accounts", "GET /v2/accounts/{accountId}  returns { id, name, currency }"),
    ("invoices", "GET /v2/invoices/{invoiceId}  returns { id, total, currency }"),
]
E14_ORDERS = [
    ["correct"] + [k for k, _ in E14_OPTIONS[1:]],
    [k for k, _ in E14_OPTIONS[1:4]] + ["correct"] + [k for k, _ in E14_OPTIONS[4:]],
    [k for k, _ in E14_OPTIONS[1:]] + ["correct"],
]


def _numbered_prompt(order: list[str], codes: list[str], text: dict[str, str]) -> str:
    lines = "\n".join(f"{codes[i]}: {text[k]}" for i, k in enumerate(order))
    return f"{OLD_ENDPOINT}\n\nWhich new endpoint is the same operation?\n{lines}"


def _stage1(exp: str, order: list[str], codes: list[str],
            text: dict[str, str]) -> dict[str, Any]:
    import math
    r = chat(exp, messages=[{"role": "system", "content": SYSTEM_CHOICE},
                            {"role": "user", "content": _numbered_prompt(order, codes, text)}],
             **BASE)
    out: dict[str, Any] = {"ok": r["ok"]}
    if not r["ok"]:
        out["error"] = flat_err(r)
        return out
    lps = lp_content(r)
    top = lps[0]["top_logprobs"]
    table = toks_in(top)
    correct_code = codes[order.index("correct")]
    # map every returned token back to a code, keep the raw probabilities
    per_code: dict[str, list[tuple[str, float]]] = {}
    for code in codes:
        for variant in (code, f" {code}", f"{code}.", f" {code}."):
            if variant in table:
                per_code.setdefault(code, []).append((variant, table[variant]))
    visible = sorted(per_code, key=lambda c: max(v for _, v in per_code[c]), reverse=True)
    mass_codes = sum(math.exp(v) for c in per_code for _, v in per_code[c])
    dist = probs_over(top, codes)
    out.update(
        first_token=lps[0]["token"],
        prompt_tokens=(r["resp"].get("usage") or {}).get("prompt_tokens"),
        top_logprobs=[{"token": t["token"], "logprob": t["logprob"],
                       "prob": math.exp(t["logprob"])} for t in top],
        correct_code=correct_code,
        visible_codes=visible,
        n_visible=len(visible),
        distribution=dist,
        p_correct=dist.get(correct_code),
        p_correct_absolute=math.exp(table[correct_code]) if correct_code in table else None,
        mass_on_codes=mass_codes,
        mass_other=1 - mass_codes,
        winner_letter=next((c for c in visible), None),
        winner_is_correct=bool(visible) and visible[0] == correct_code,
    )
    return out


def _choice_set(exp: str, options: list[tuple[str, str]], orders: list[list[str]]) -> dict[str, Any]:
    text = dict(options)
    rows = []
    for i, order in enumerate(orders, start=1):
        codes = list(LETTERS10[: len(order)])
        s1 = _stage1(exp, order, codes, text)
        row: dict[str, Any] = {"order": i, "n_options": len(order),
                               "correct_letter": codes[order.index("correct")],
                               "stage1": s1}
        if not s1["ok"]:
            rows.append(row)
            continue
        # stage 2: re-ask only the candidates stage 1 actually revealed
        shortlist = s1["visible_codes"]
        if len(shortlist) >= 2 and s1["correct_code"] in shortlist:
            sub_order = [dict(zip(codes, order))[c] for c in shortlist]
            s2 = _stage1(exp, sub_order, list(LETTERS10[: len(sub_order)]), text)
            row["stage2"] = s2
            if s2["ok"]:
                new_letter = LETTERS10[sub_order.index("correct")]
                p_within = s2["distribution"].get(new_letter)
                row["stage2_shortlist"] = dict(zip(list(LETTERS10[: len(sub_order)]), sub_order))
                row["stage2_p_correct"] = p_within
                row["combined_p_correct"] = (p_within * s1["mass_on_codes"]
                                             if p_within is not None else None)
        else:
            row["stage2"] = {"skipped": "correct code not visible in stage 1"}
            row["combined_p_correct"] = 0.0
        rows.append(row)
    ok_rows = [r for r in rows if r["stage1"]["ok"]]
    return {
        "rows": rows,
        "n_options": len(options),
        "correct_wins_all_orders": all(r["stage1"]["winner_is_correct"] for r in ok_rows),
        "n_visible_per_order": [r["stage1"]["n_visible"] for r in ok_rows],
        "p_correct_stage1": [r["stage1"]["p_correct"] for r in ok_rows],
        "mass_other_per_order": [r["stage1"]["mass_other"] for r in ok_rows],
        "combined_p_correct": [r.get("combined_p_correct") for r in rows],
    }


def e12() -> dict[str, Any]:
    """10 options, including one deliberate near-duplicate distractor."""
    return _choice_set("E12", E12_OPTIONS, E12_ORDERS)


def e14() -> dict[str, Any]:
    """10 options, no near-duplicate: the clean version of the same question."""
    return _choice_set("E14", E14_OPTIONS, E14_ORDERS)


# --------------------------------------------------------------------------- #
# E15 -- why the two-stage shortlist degraded: is "None of these" the culprit?
# --------------------------------------------------------------------------- #
E15_SETS = {
    "with none (3 options)": [("correct", OPTION_TEXT["clients_by_id"]),
                              ("none", OPTION_TEXT["none"]),
                              ("list_clients", OPTION_TEXT["list_clients"])],
    "without none (2 options)": [("correct", OPTION_TEXT["clients_by_id"]),
                                 ("list_clients", OPTION_TEXT["list_clients"])],
    "only correct + none": [("correct", OPTION_TEXT["clients_by_id"]),
                            ("none", OPTION_TEXT["none"])],
}


def e15() -> dict[str, Any]:
    rows = []
    for label, opts in E15_SETS.items():
        order = [k for k, _ in opts]
        r = _stage1("E15", order, list(LETTERS10[: len(order)]), dict(opts))
        rows.append({"variant": label, "n_options": len(opts), "ok": r["ok"],
                     "top_logprobs": [(t["token"], round(t["logprob"], 4)) for t in r.get("top_logprobs", [])],
                     "p_correct": r.get("p_correct"), "winner_correct": r.get("winner_is_correct"),
                     "error": r.get("error")})
    return {"rows": rows,
            "p_correct_by_variant": {r["variant"]: r["p_correct"] for r in rows}}


# --------------------------------------------------------------------------- #
# E13 -- same 10 options, 2-digit codes (01..10), tokenisation comparison
# --------------------------------------------------------------------------- #
def e13() -> dict[str, Any]:
    codes = [f"{i:02d}" for i in range(1, len(E14_OPTIONS) + 1)]
    s1 = _stage1("E13", E14_ORDERS[0], codes, dict(E14_OPTIONS))
    return {"codes": codes, "stage1": s1,
            "single_token_codes": s1.get("visible_codes"),
            "p_correct": s1.get("p_correct")}


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
EXPERIMENTS = {"E0": e0, "E1": e1, "E2": e2, "E3": e3, "E4": e4, "E5": e5,
               "E6": e6, "E7": e7, "E8": e8, "E9": e9, "E10": e10, "E11": e11,
               "E12": e12, "E13": e13, "E14": e14, "E15": e15}


def main() -> None:
    global MODEL, CLIENT
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", nargs="*", default=None, help="subset, e.g. --exp E1 E4")
    ap.add_argument("--model", default=MODEL)
    args = ap.parse_args()
    MODEL = args.model
    CLIENT = client()

    wanted = args.exp or list(EXPERIMENTS)
    for name in wanted:
        fn = EXPERIMENTS.get(name)
        if fn is None:
            print(f"{name}: no such experiment", file=sys.stderr)
            continue
        print(f"\n=== {name} ===", flush=True)
        res = fn()
        RESULTS[name] = res
        print(json.dumps(res, indent=2)[:4000], flush=True)

    prev = {}
    p = Path(__file__).parent / "results.json"
    if p.exists():
        try:
            prev = json.loads(p.read_text())
        except json.JSONDecodeError:
            prev = {}
    prev.update({"model": MODEL, "base_url": BASE_URL, **RESULTS})
    p.write_text(json.dumps(prev, indent=2))
    print(f"\nwrote {p}")


if __name__ == "__main__":
    main()
