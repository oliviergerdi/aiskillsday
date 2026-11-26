# nParity: Prototype Design

Nov 26, 2026 · Gerdi + Claude · brainstorm output, **approved 08:48** (with the batching and mapping-findings amendments below)

Builds on `nparity-build-spec.md` (goal, toy demo, demo story) and `nparity-evaluator-spec.md` (LLM layer). Where this doc disagrees with them, this one wins. Next step after approval: an implementation plan (`docs/nparity-plan.md`).

## Intent

Show a **working prototype** on Friday: point nParity at an old and a new HTTP service, and it tells you which differences matter, how sure it is, and why. It's a prototype, not a product, so anything that doesn't make the demo work or make it convincing is out of scope.

## Goals

1. End-to-end run from the CLI from the first hour (walking skeleton), using `FakeBackend`.
2. Web UI from the first hour: a place to *read* findings, not just a terminal dump.
3. Flash (Fireworks) plugs in behind the evaluator interface without touching the pipeline.
4. Score against the answer key on every run.
5. Survive Fireworks dropping requests (retry with backoff, per call).

## Non-goals (not today)

- Deployment, hosting, Render or anything like it. Runs locally: `uvicorn` + CLI.
- Auth, passwords, secrets handling beyond reading `FIREWORKS_API_KEY` from env. Placeholders at most.
- Starting runs from the web UI (stretch, see below).
- Jev and SampleVote backends: interface leaves room, no code.
- Real request generation from arbitrary OpenAPI specs with fake data.
- Databases, queues, background workers.

## Anti-goals (don't do even if there's time)

- Letting the LLM judge numbers, rounding, counts or pagination. That's the differ's job.
- Re-asking the LLM a trimmed shortlist (logprobs report §3.3).
- Yes/no questions for mapping (report E5).
- Logic in the front ends. CLI and web only render a saved run.

## Constraints

- Python 3.14 via mise/asdf, Poetry 2.x, `package-mode = false` (README). The build spec's "3.12" is stale.
- Build Thu 26 Nov 09:15–17:00, demo Fri 27 Nov 10:00. Toy services only: no docfox code, data or credentials.
- Claude can't run the code. Claude writes code + pytest tests; Gerdi runs them and reports back. Tests must be deterministic and key-free by default.
- Storage is **YAML** throughout (runs, cache, fixtures, config).

## Stack

| Part | Choice |
|---|---|
| Web + toy services | FastAPI, served by uvicorn |
| Report UI | Jinja2 + HTMX (CDN script tag); stylesheet lifted from `docs/mockups/web-ui.html` (no Pico, no build) |
| CLI | Typer |
| HTTP | httpx (sync) + `ThreadPoolExecutor` for concurrency |
| Types | pydantic v2 |
| Storage | PyYAML |
| Tests | pytest; FastAPI `TestClient` (an httpx client) to replay against the toy apps in-process |

Sync + threads over async: simpler to debug in a day, and "retry per thread" falls out naturally. Concurrency cap 8.

## Pipeline

```
seeds.yaml + v1 OpenAPI ─► generate ─► requests
v1 + v2 OpenAPI ─────────► map (rules, then LLM for leftovers) ─► endpoint + field mapping
requests + mapping ──────► replay old/new (retry) ─► response pairs
response pairs ──────────► normalise (noise rules + accepted renames) ─► diff
diff + schemas ──────────► type check (observed + declared) ─► findings
findings + intent.md ────► triage (LLM) ─► labels + p(winner)
everything ──────────────► Run ─► runs/<id>.yaml ─► CLI summary / web UI
                                                └─► score vs answer_key.yaml
```

### 1. Generate requests

- Endpoints and parameters come from the **v1 OpenAPI spec** (FastAPI generates it).
- Values come from `fixtures/seeds.yaml`, keyed by parameter name. The generator crosses them, capped at ~5 requests per endpoint. Target: at least 1, preferably 2–5 samples per endpoint.
- Request bodies for POST come from `seeds.yaml` too (one or two per endpoint).
- Behind a `RequestSource` interface so a smarter generator can replace it later.

```yaml
# fixtures/seeds.yaml
params:
  id: [1, 2, 999]          # 999 = not found
  page: [1, 2]
bodies:
  "POST /orders":
    - { customerId: 1, items: [{ sku: "A1", qty: 2 }] }
```

### 2. Map old → new (rules first, LLM for leftovers)

**Endpoints**

1. Candidates = v2 endpoints with the same method.
2. Filter by path tokens (`/customers/{id}` → `customer` stem in v2 path) and path-parameter count.
3. Exactly one left → accepted **by rule** (`source: rule`, no probability).
4. Several left → one LLM `choice` question with the full filtered list (≤30, deduped near-duplicates, plus `none`).
5. None left → widen to all same-method v2 endpoints and ask the LLM once. This is how `/customers/{id}` → `/clients/{clientId}` gets found.
6. More than 30 candidates after filtering → **batched tournament** (below).
7. Path params are carried over by position.

**Batched tournament (lists over 30)**

Split into batches of ≤30 (each with `none`), take the top 3 from each, then ask once over the finalists. Guardrails, because the logprobs report measured that a re-asked shortlist changes the probabilities (§3.3, E15: 0.998 → 0.44; `None of these` soaks up the mass):

- No `none` in the final round. "No match" is decided in the batch round: if every batch's winner is `none`, the endpoint is unmapped.
- A final-round result is **never auto-accepted** on its own probability. It's `accepted` only if the final winner also won its batch with p ≥ `auto_accept`; otherwise `review`.
- Recorded as `source: llm_tournament` with both rounds' probabilities, and shown as such in the UI.
- Not exercised by the toy demo (5–6 endpoints). Validated by a live probe in `proto/` against the E8 30-option set before anyone relies on it.

**Fields** (per mapped endpoint pair, from response schemas)

1. Exact name match → mapped by rule.
2. Leftover old fields → one LLM `choice` per field over the leftover new fields plus `none` (→ dropped).
3. Thresholds from `config/thresholds.yaml`: auto-accept at p ≥ 0.95, review ≥ 0.50, else unmapped.

Mapping results are recorded with `source: rule | llm` so the UI and the demo can say "the model only handled N of M decisions".

### 3. Replay

- Each request goes to old; the mapped request (path, renamed params) goes to new.
- Base URLs from CLI flags. In tests, the toy apps are replayed in-process via `TestClient`.
- Retry policy (shared with the LLM backend, see below).

### 4. Normalise

Deterministic rules from `config/noise.yaml`, applied to both sides before diffing:

- Mask fields by JSON path (`$.id`, `$.createdAt`) or by pattern (ISO timestamps, UUIDs).
- Sort lists of objects by a key, or by full content, when the path is marked unordered.
- Apply accepted field renames from step 2 (old name → new name), so a rename alone doesn't show up as a diff.

### 5. Diff + type check (deterministic)

Value diff per JSON path: `changed`, `missing_in_new`, `added_in_new`, `status_changed`, `list_length_changed`.

Type checks, both kinds:

- **Observed:** across all samples, per field path, compare JSON types: string / integer / decimal / boolean / null / array / object, null vs missing, decimal precision (10.01 vs 10.0).
- **Declared:** for mapped field pairs, compare OpenAPI schemas: type, format, required, nullable, enum values. Applies to fields the samples never exercised.
- A disagreement between declared and observed on either side is reported too.

**Mapping decisions become findings too.** An endpoint move or a field rename/drop accepted by the mapper is emitted as a finding with `kind: moved | renamed | dropped` and `source: mapping`, and triaged against the intent note like any other. Normalising still applies the rename so it doesn't *also* show up as a value diff. This puts every answer-key item on the run page.

Raw diffs are **grouped into findings** by (endpoint pair, JSON path, kind) across samples. One finding = one triage decision, with every sample attached as evidence. That keeps LLM calls proportional to distinct problems, not to sample count.

### 6. Triage (LLM)

- One `choice` question per finding: `intended` / `regression` / `unsure`, against `fixtures/intent.md` (free text).
- State = intent note + finding (kind, path, old and new values from the first 1–3 samples, type info).
- Labels and thresholds per the evaluator spec: intended auto-accepted at p ≥ 0.98; regression always shown; below threshold → `unsure`.
- Reasons: second optional call, only for findings the report shows (regressions and unsure), `max_tokens: 60`.
- Noise items never reach triage. They're recorded as `noise` with the rule that removed them.

### 7. Run + score

The whole run is one pydantic `Run` model, saved as `runs/<timestamp>-<slug>.yaml`.

```yaml
id: 2026-11-26T1105-toy
started_at: ...
config: { old: ..., new: ..., backend: fake, profile: null }
mapping:
  endpoints:
    - { old: "GET /customers/{id}", new: "GET /clients/{clientId}", source: llm, p: 0.997, status: accepted, top3: [...] }
  fields:
    - { endpoint: "GET /customers/{id}", old: fullName, new: name, source: llm, p: 0.99, status: accepted }
findings:
  - id: f-006
    endpoint: "GET /orders/{id}"
    path: $.total
    kind: changed
    samples: [{ request: ..., old: { status: 200, body: ... }, new: { ... } }]
    label: regression
    p: 0.991
    status: shown          # accepted | shown | unsure | noise | error
    reason: "Total rounded down; intent says nothing else should change."
score: { correct: 10, total: 10, unsure: 1, false_regressions: 0, details: [...] }
telemetry: { llm_calls: 14, rule_decisions: 22, seconds: 31.2, cost_usd: 0.0011, retries: 2 }
```

Scoring matches findings and mapping decisions against `fixtures/answer_key.yaml`:

```yaml
mapping:
  - { old: "GET /customers/{id}", new: "GET /clients/{clientId}" }
  - { endpoint: "GET /customers/{id}", old_field: fullName, new_field: name }
  - { endpoint: "GET /customers/{id}", old_field: legacyCode, new_field: null }
findings:
  - { endpoint: "GET /orders/{id}", path: $.total, expect: regression }
  - { endpoint: "GET /orders", path: "$[*]", expect: noise }
```

## LLM layer

As per `nparity-evaluator-spec.md`, scoped down for today:

- `evaluate(state, questions) -> {id: Answer}`, Jev-shaped.
- **Built:** `LogprobChatBackend` + Fireworks Flash profile (`config/profiles/flash.yaml`), `FakeBackend` (answers from the answer key), `Cached` decorator (YAML file per question, key = hash of backend, profile, version, template version, state, question).
- **Not built:** Jev, SampleVote.
- Selected by `NPARITY_LLM=fake|flash`, default `fake`.
- Telemetry per call: latency, tokens, cached tokens, cost, retries.

### Retry (LLM and replay)

- Per call, inside the worker thread: exponential backoff with full jitter, base 0.5 s, cap 8 s, max 4 attempts.
- Retry on: 408, 429, 500, 502, 503, 504, 529, timeouts, connection errors (resets, remote disconnects).
- Don't retry other 4xx (e.g. 400 for a bad `top_logprobs`): that's a bug.
- Exhausted → the item is recorded with `status: error` and the error text. The run continues and the UI shows it.
- Retries counted into telemetry.
- Implemented once as a small helper (no extra library), tested with a fake transport that fails N times.

## Front ends

Both only read `Run` YAML. No analysis in either.

### CLI (Typer)

```
nparity run --old URL --new URL --intent fixtures/intent.md [--seeds ...] [--backend fake|flash]
nparity show RUN_ID           # summary of a saved run
nparity runs                  # list saved runs
```

`run` prints counts, then regressions, then unsure (one line each: endpoint, path, label, p, reason), the answer-key score, the telemetry line, and the web URL for the run.

### Web UI (FastAPI + Jinja + HTMX)

Same FastAPI app as the toy services: `/v1/*`, `/v2/*` are the toys, everything else is nParity.

| Page | Shows |
|---|---|
| `/` | List of saved runs: time, backend, counts, score |
| Reference | `docs/mockups/web-ui.html` is the approved look for all pages below |
| `/runs/{id}` | Header counts (regression / unsure / intended / noise / error), answer-key score, telemetry footer. Findings grouped: regressions, unsure, intended, noise, errors |
| finding row → expand (HTMX partial) | Request; old and new responses side by side with the differing path highlighted; type info; label, p(winner) against its threshold; reason; per-sample list |
| `/runs/{id}/mapping` | Endpoint mapping and field mapping tables: old → new, source (rule/llm), p, status, top-3 alternatives |

View-only. A "Run now" button is a stretch item; if built, no auth, and a placeholder comment where auth would go.

## Toy services

As in the build spec (10 seeded differences, intent note unchanged). In-memory data, two FastAPI routers mounted at `/v1` and `/v2`, each producing its own OpenAPI spec. v2 moves customers to `/clients/{clientId}`. Seed data must make every difference reachable from `seeds.yaml` (e.g. one customer type without `currency`, an order totalling 10.005, enough orders for a page 2).

## Layout

```
nparity/
  models.py            pydantic: Request, Response, Mapping, Finding, Run, AnswerKey
  generate.py  map.py  replay.py  normalise.py  diff.py  types.py  triage.py  score.py
  pipeline.py          wires the steps, returns Run
  store.py             YAML read/write for runs
  retry.py
  evaluator/
    base.py  logprob_chat.py  fake.py  cache.py  profiles.py
  cli.py
app/
  main.py              FastAPI: mounts toys + web
  toys/v1.py  toys/v2.py  toys/data.py
  web/routes.py  web/templates/*.html
config/
  thresholds.yaml  noise.yaml  profiles/flash.yaml
fixtures/
  intent.md  seeds.yaml  answer_key.yaml
runs/                  saved runs (gitignored except a frozen demo run)
cache/                 LLM cache (YAML)
tests/
proto/                 existing logprobs probe, untouched
```

## Testing

- `poetry run pytest` runs everything against `FakeBackend` and the toy apps in-process. No key, no network, deterministic.
- Unit tests per step (generate, map rules, normalise, diff, type checks, grouping, scoring, retry, logprob parsing from the recorded `proto/raw/E4_1.json`).
- One end-to-end test: full pipeline on the toy services with `FakeBackend` → expects 10/10 on the answer key.
- Web smoke tests: each page returns 200 and contains key strings.
- `@pytest.mark.live` tests hit Fireworks; skipped unless `FIREWORKS_API_KEY` is set. Gerdi runs them manually and reports.

## Approaches considered

| Decision | Chosen | Rejected, and why |
|---|---|---|
| First slice | Walking skeleton, fake LLM, whole pipeline + web | Deterministic core first: no demo-able run until late |
| Web role | View saved runs | Trigger runs: background task + progress state, not worth it for the first slice |
| Storage | YAML | JSON / SQLite: Gerdi's preference; YAML is readable and diffable |
| Requests | OpenAPI endpoints × `seeds.yaml` values | Hand-written list: not generic; full OpenAPI data generation: an hour of risk |
| Mapping | Rules first, LLM for ambiguous leftovers; guarded tournament past 30 | LLM for everything: slower, costlier, more to tune |
| Type check | Observed + declared | Either alone misses a class of break |
| Concurrency | Sync httpx + threads | Async: harder to debug in a day |
| Deployment | None, local | Render: never approved |

## Defaults I picked (shout if wrong)

1. Findings grouped by (endpoint pair, path, kind) across samples; one triage call per finding.
2. Intent note is free-text Markdown.
3. Mockup CSS + HTMX from CDN; no front-end build.
4. Cache and runs are YAML files on disk; one frozen demo run committed.
5. Default backend `fake`; Flash opt-in by env/flag.

## Left to the builder

Exact prompt wording for triage (Temba), page copy, exact noise patterns, CSS polish.

## Stretch, only if ahead

"Run now" button; accepted-differences ledger; learned noise rules; OpenAPI-driven data generation.
