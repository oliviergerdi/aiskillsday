# nParity: Build Spec v2

Nov 25, 2026 · Gerdi, building on Stevo's handoff (Nov 24)

This is Stevo's handoff with what we've learned since folded in. Where the two disagree, this one wins. Detail lives in three companion files in this folder:

- `logprobs_report.md`: what Fireworks + DeepSeek Flash can and can't do, measured
- `nparity-evaluator-spec.md`: the swappable, Jev-shaped LLM layer
- `nparity-llm-layer-sketch.md`: the earlier Ruby sketch, superseded by the evaluator spec

## What changed since the handoff

| Area | Handoff said | Now |
| --- | --- | --- |
| LLM | Open | Fireworks, DeepSeek V4.1 Flash, `-us` router, reasoning off. Tested: about $0.00007 and 0.6 s per call |
| How the LLM answers | JSON with a label and a reason | Picks a label by reading logprobs (one token), so every label carries a real probability. Reasons come from a second, optional call, only for items shown in the report |
| Unsure | A label the LLM picks | Picked explicitly, **or** derived from low confidence. Thresholds tuned against the answer key |
| LLM layer | One provider | Swappable, Jev-shaped interface: Flash for the event, Jev later, a fake backend for tests and an offline fallback |
| Renames | Declared in the intent note | Also **discovered** by a mapping step (endpoints and fields, old to new, ranked with confidence). The intent note says which changes are wanted; the mapper finds what changed |
| Stack | Open | Python 3.12 + FastAPI, CLI and web on one engine (proposed, confirm at 09:15) |
| Hosting | Open | Render free tier (proposed) |

## Goal and constraints

Unchanged from the handoff: build Thu 26 Nov 09:15–17:00, demo Fri 27 Nov 10:00 (5–10 minutes plus 2 minutes Q&A, recording allowed). Toy services only, no docfox code, data or credentials. CSOM → Mesh is motivation only, in aggregate.

## What nParity is

nParity answers "Will we break anything?" when a team rewrites a service. It sends the same requests to the old and new HTTP services, works out which differences matter, and shows how sure it is about each one. The users are backend engineers, and the managers who sign off on a cutover.

Answer to "isn't this Diffy or Scientist?": those tools replay and diff. nParity adds three things: it maps old to new when the shapes differ, it removes noise, and it triages each difference against stated intent, with a confidence a reviewer can act on. The reviewer reads a handful of items, not a wall of diffs.

## Pipeline

1. **Generate requests** from the old service's OpenAPI spec (FastAPI provides it).
2. **Map old to new** (LLM). For each old endpoint, rank the most likely new endpoint and keep the top 3. For each matched pair, map request and response fields. Auto-accepted at p(winner) ≥ 0.95; otherwise review or unmapped.
3. **Replay** each request against old, and the mapped request against new.
4. **Normalise noise**: timestamps, generated IDs, list ordering, whitespace, and the field renames accepted in step 2.
5. **Diff** what remains, deterministically. Numbers, rounding, counts and pagination are caught here, never by the LLM.
6. **Triage** each difference against the intent note (LLM): intended, regression or unsure. "Intended" is auto-accepted only at p ≥ 0.98. Regressions are always shown, never auto-dismissed. Anything below its threshold becomes unsure.
7. **Report**: counts first, then regressions, then unsure items, each with the request, both responses, confidence and a one-line reason. Then agreement with the answer key, then cost and time for the run.

### Rules learned from testing (`logprobs_report.md`)

- Turn reasoning off (`reasoning_effort: "none"`). Without it there is no answer.
- At most 5 options gives a real probability. Up to about 30 still picks the right answer, but as a ranking, flagged `censored`.
- Ask once with the full option list. Never re-ask a trimmed shortlist (the same answer dropped from 0.998 to 0.44).
- Remove near-duplicate options before asking. They tie exactly.
- Don't map with yes/no ("is X the same as Y?"). The model reads it as strict identity and says no to correct renames.
- Results jitter slightly between runs, so the cache is what makes the demo repeatable.
- Thresholds apply to p(winner), the winner's raw probability, and are set per decision type and per model: mapping 0.95, intended 0.98, regressions never auto-dismissed. Flash isn't calibrated, so these are conservative starting points, checked against the answer key (details in the evaluator spec).

## Architecture

One FastAPI app, one deployment, no queue, no database.

```
nparity/                      Python package, the engine
  evaluator/                  Jev-shaped LLM layer (see evaluator spec)
    backends: logprob_chat (Fireworks profile), jev, fake
    cache: file-based, keyed per question
  generate.py  map.py  replay.py  normalise.py  diff.py  triage.py  report.py
  cli.py                      nparity run --old URL --new URL --intent intent.md
app/                          FastAPI
  /v1/...  /v2/...            toy services, each with its own OpenAPI spec
  /                           report page (Jinja + a little HTMX)
  /run                        live run, password-protected
fixtures/
  intent.md  answer_key.yaml
```

- **CLI and web share the engine.** The pitch line: "the same engine runs in your CI on every deploy."
- **The public page shows the cached run by default.** Live re-runs sit behind a password so nobody burns the key from a shared link. The Fireworks key stays server-side.
- **The LLM layer is swappable** by one setting: `NPARITY_LLM=flash|jev|fake`. The fake backend answers from the answer key, for tests and as the offline demo fallback.
- **Library option:** fork `jevper` (Apache-2.0) as the Flash backend if it passes the conformance probe with `top_logprobs` patched to 5. Otherwise write the ~100 lines in the evaluator spec.

## Stack

| Part | Choice | Why |
| --- | --- | --- |
| Language | Python 3.12 | Fireworks client already proven in `logprobs_test.py`; Jev tooling exists in Python |
| Web | FastAPI | Generates the OpenAPI spec for both toy services |
| Report UI | Jinja + HTMX | Server-rendered, no front-end build |
| CLI | Typer | Small, pairs with FastAPI |
| HTTP | httpx | Async replay and LLM calls |
| Types | pydantic | Questions, answers, diffs, answer key |
| Tests | pytest, against the fake backend | Deterministic |
| Hosting | Render free tier | One service, outbound calls allowed. Spins down when idle, so open it a minute before the demo |

## Toy demo design

Same as the handoff, with one change: v2 moves one path, so the mapper has something to find.

Intent note: "The rewrite renames `fullName` to `name`, moves customers to `/clients`, returns 201 on create, and drops the deprecated `legacyCode` field. Nothing else should change."

| # | Endpoint | Difference between old and new | Expected outcome | Caught by |
| --- | --- | --- | --- | --- |
| 1 | GET /orders | List items in a different order | Noise | normaliser |
| 2 | POST /orders | `id` and `createdAt` differ every call | Noise | normaliser |
| 3 | POST /orders | Status 200 becomes 201 | Intended | triage |
| 4 | GET /customers/{id} | `fullName` renamed `name` | Intended | mapper + triage |
| 5 | GET /customers/{id} | `legacyCode` dropped | Intended | mapper (unmapped) + triage |
| 6 | GET /orders/{id} | `total` 10.005 rounds to 10.00, was 10.01 | Regression | differ + triage |
| 7 | GET /orders?page=2 | Last page empty (off by one) | Regression | differ + triage |
| 8 | GET /customers/{id} | `currency` missing for one customer type | Regression | differ + triage |
| 9 | GET /orders/{id} (not found) | Error message wording changed | Unsure | triage (low confidence) |
| 10 | GET /customers/{id} | Moved to `GET /clients/{clientId}` | Intended | mapper |

The answer key is data (`answer_key.yaml`) covering both mapping and triage. The report scores nParity against it, for example: "10/10 correct, 1 flagged unsure, 0 false regressions."

Difference #6 is worth a sentence in the demo: 10.005 can't be stored exactly as a float, so naive rounding really does produce 10.00.

## Prep before Thursday 09:15

**Admin, safe now**

- [x] LLM provider tested: Fireworks works, see `logprobs_report.md`
- [ ] Confirm whose Fireworks key we use on the day and whether a shared key is allowed
- [ ] Confirm stack (Python + FastAPI) with Stevo and Temba
- [ ] Create the public repo, README only
- [ ] Deploy a hello-world FastAPI app to Render; confirm it can call Fireworks
- [ ] Python 3.12 runs on your laptop (it does: `.tool-versions`)
- [ ] Test the jevper fork against the conformance probe (testing a library, not building the product)

**Build, still on hold until the organisers confirm**

- [ ] Toy services, intent note, answer key
- [ ] Engine, triage prompts, report page
- [ ] Skeleton demo video

## Thursday plan

Claude writes most of the code, with Gerdi driving and reviewing. Owners below are for decisions and review.

1. **09:15–09:45, align.** Lock intent note, answer key and stack. Stevo: deck and commercials. Gerdi: engine. Temba: triage questions and the report page's wording.
2. **09:45–11:00, core.** Toy services, generator, replayer, normaliser, differ, end to end on the deterministic differences (1, 2, 6, 7, 8).
3. **11:00–12:15, LLM.** Evaluator with Flash backend and cache, then mapping (4, 5, 10) and triage (3, 9).
4. **12:15–13:00, report.** Report page, answer-key scoring, cost footer.
5. **13:30–14:30, tune and deploy.** Run against the key, check nothing wrong lands above the thresholds (0.95 / 0.98), warm and freeze the cache, deploy to Render.
6. **14:30–16:00, commercials and fallback.** Deck numbers; record the demo video.
7. **16:00–17:00, rehearse.** Demo and Q&A twice, then freeze.

## Stretch, only if ahead

- **Accepted-differences ledger.** Confirmed or overridden labels are saved, so later runs only surface new differences, with an audit trail for whoever signs off the cutover.
- **Learned noise rules.** The LLM proposes masking for fields that change on every call ("`$.id` looks generated, mask it?"). Once accepted, they run without the LLM.
- **Second backend live.** Rerun the same check on another model and compare agreement with the answer key.

## Demo story (5–10 minutes)

1. The problem: a rewrite, hundreds of endpoints, "Will we break anything?"
2. One click: 10 differences found, 2 removed as noise, 3 intended, 3 regressions, 1 unsure, 1 endpoint move discovered.
3. Open a regression: request, both responses, reason, confidence.
4. Show the score against the answer key, and the cost footer (cents for the whole run).
5. Close: the same engine runs in CI, and it's model-agnostic, so it runs on whatever the company has approved.

## Q&A answers to have ready

- **Diffy or Scientist?** They diff. We map, filter and triage against intent, with confidence.
- **Does it scale to a real API?** Shortlist candidates deterministically, then rank with the model. Measured: correct at 30 candidates in one call.
- **Why trust the AI?** We measured it: the answer key score is on screen, and low-confidence items go to a human. The bar is higher where a mistake costs more: 95% to accept a mapping, 98% to wave a difference through as intended, and a regression is never dismissed automatically.
- **Which model?** Any. It runs on DeepSeek Flash today, through a swappable layer.

## Open questions

- [ ] Stevo: does writing toy services and fixtures before 09:15 count as pre-work?
- [ ] Gerdi: whose Fireworks key, and is sharing it allowed?
- [ ] All: stack confirmed as Python + FastAPI?
- [ ] Gerdi and Stevo: live demo with recorded fallback, or recording only?
- [ ] Stevo: deck placeholders (quotes, engineer-weeks, day rate, price)
