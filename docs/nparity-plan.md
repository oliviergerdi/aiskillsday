# nParity Prototype Implementation Plan

> **For agentic workers:** execute with superpowers:executing-plans (native: one session builds, Gerdi runs tests and reviews). Steps use `- [ ]` checkboxes. Claude cannot run code here: every "Run" step is Gerdi's, who reports the output back.

**Goal:** a working local prototype that replays the toy v1/v2 services, maps, diffs, type-checks and triages the differences, and shows the run in a CLI summary and a web UI, scoring 10/10 against the answer key.

**Architecture:** one Python package (`nparity/`) holds the pipeline and the Jev-shaped evaluator; one FastAPI app (`app/`) hosts the toy services at `/v1` and `/v2` plus the web UI. Every run is a pydantic `Run` saved as YAML; CLI and web only render it. Walking skeleton first on `FakeBackend`, Flash plugged in after.

**Tech stack:** Python 3.14 (mise/asdf), Poetry 2.x, FastAPI, uvicorn, Typer, httpx (sync), pydantic v2, Jinja2, HTMX (CDN), PyYAML, pytest.

**Spec:** `docs/nparity-design.md` (approved). Supporting: `docs/nparity-evaluator-spec.md`, `docs/logprobs_report.md`, `docs/mockups/web-ui.html`.

## Global constraints (from the spec, apply to every task)

- Prototype over product: no auth, no deployment, no database. Placeholders at most.
- Storage is YAML (runs, cache, fixtures, config).
- Tests are deterministic and key-free by default; `@pytest.mark.live` tests skip unless `FIREWORKS_API_KEY` is set.
- The LLM never judges numbers, rounding, counts or pagination; the differ does.
- Never re-ask a trimmed shortlist as if it were calibrated; never use yes/no for mapping; dedupe near-duplicate options; `reasoning_effort: none`; `top_logprobs: 5`.
- Retry per call: exponential backoff, full jitter, base 0.5 s, cap 8 s, 4 attempts, on 408/429/500/502/503/504/529, timeouts and transport errors. Exhausted → `status: error`, run continues.
- Front ends contain no analysis.

## Review focus (failure modes no single task obviously owns)

1. **Rename applied twice or not at all**: a mapped rename must vanish from the value diff *and* appear once as a `renamed` finding. → Task 7 test.
2. **Noise rule hides a real regression**: sorting `$.items` must not hide page 2 being empty. → Task 7 test.
3. **Float formatting in YAML**: `10.0` vs `10.00` vs `10.005` must survive a store round trip unchanged. → Task 1 test.
4. **Answer-key matching on paths**: `$.items` vs `$.items[*]` vs `$.items[0].id` must match the intended item only. → Task 8 test.
5. **One failing request kills the run**: an exhausted retry on one sample must produce an `error` item and leave the other findings intact. → Task 9 test.

## File structure

```
pyproject.toml                  + deps, pytest config (Task 0)
nparity/
  models.py                     all pydantic types: Request, Sample, EndpointMap, FieldMap, Finding, Noise, Score, Telemetry, Run, AnswerKey
  store.py                      Run <-> runs/<id>.yaml
  retry.py                      RetryPolicy, retry_call, is_retryable
  openapi.py                    load spec, list endpoints, response schema per endpoint
  generate.py                   OpenAPI x seeds -> list[Request]
  map.py                        endpoint + field mapping (rules, LLM, tournament)
  replay.py                     send old/new with retry -> list[Sample]
  normalise.py                  noise rules + renames -> (normalised pair, list[Noise])
  diff.py                       value diffs per JSON path
  types.py                      observed + declared type checks
  findings.py                   group diffs + mapping decisions into Findings
  triage.py                     build questions, apply thresholds
  score.py                      Run vs AnswerKey
  pipeline.py                   run(config, evaluator) -> Run
  config.py                     load thresholds.yaml, noise.yaml, seeds.yaml
  cli.py                        Typer app
  evaluator/
    base.py                     Question, Answer, Capabilities, Backend protocol, build()
    fake.py                     FakeBackend (answer key)
    cache.py                    Cached decorator, YAML files
    logprob_chat.py             LogprobChatBackend + parse_top_logprobs
    profiles.py                 Profile model + loader
app/
  main.py                       FastAPI: mount /v1, /v2, web
  toys/data.py  toys/v1.py  toys/v2.py
  web/routes.py
  web/templates/base.html runs.html run.html finding.html mapping.html
  web/static/nparity.css        lifted from docs/mockups/web-ui.html
config/thresholds.yaml  config/noise.yaml  config/profiles/flash.yaml
fixtures/intent.md  fixtures/seeds.yaml  fixtures/answer_key.yaml
tests/ ...                      one test file per module, plus test_e2e.py, test_web.py
proto/logprobs_test.py          + E16 tournament probe (Task 12)
```

## Schedule mapping (build spec slots)

| Slot | Tasks |
|---|---|
| 09:15–09:45 align | Task 0, agree fixtures (Task 2 data) |
| 09:45–11:00 skeleton | Tasks 1–9: end to end on `FakeBackend`, CLI prints 10/10 |
| 11:00–12:15 web | Task 10 |
| 12:15–13:30 LLM | Task 11 (Flash), live runs, warm cache |
| 13:30–14:30 tune | thresholds vs answer key, Task 13 freeze demo run |
| after, if ahead | Task 12 tournament + probe, stretch items |

---

### Task 0: Project setup

**Files:** Modify `pyproject.toml`, `.gitignore`, `README.md`. Create `nparity/__init__.py`, `nparity/evaluator/__init__.py`, `app/__init__.py`, `app/toys/__init__.py`, `app/web/__init__.py`, `tests/test_smoke.py`.

**Produces:** importable `nparity` and `app` packages; `pytest` with a `live` marker.

- [ ] Gerdi runs: `poetry add fastapi uvicorn typer httpx pydantic jinja2 pyyaml` and `poetry add --group dev pytest`. Expect: lock updated, no resolver errors on 3.14.
- [ ] Add to `pyproject.toml`:
  ```toml
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  markers = ["live: hits Fireworks; needs FIREWORKS_API_KEY"]
  pythonpath = ["."]
  ```
- [ ] `.gitignore`: `runs/*`, `!runs/demo.yaml`, `cache/`.
- [ ] `tests/test_smoke.py`: `import nparity, app`.
- [ ] Run `poetry run pytest -q`. Expect `1 passed`.
- [ ] README: add a "Running nParity" section (pytest, uvicorn, CLI); keep existing setup.
- [ ] Commit `chore: nparity skeleton and deps`.

### Task 1: Models and YAML store

**Files:** Create `nparity/models.py`, `nparity/store.py`, `tests/test_store.py`.

**Produces:**
```python
class Request(BaseModel): method: str; path: str; params: dict[str, Any] = {}; body: Any = None   # path is the template, e.g. "/orders/{id}"
class HttpResult(BaseModel): status: int | None; body: Any = None; error: str | None = None
class Sample(BaseModel): old_request: Request; new_request: Request; old: HttpResult; new: HttpResult
class EndpointMap(BaseModel): old: str; new: str | None; source: Literal["rule","llm","llm_tournament"]; p: float | None; status: Literal["accepted","review","unmapped"]; top3: list[tuple[str, float]] = []
class FieldMap(BaseModel): endpoint: str; old: str; new: str | None; source: Literal["rule","llm"]; p: float | None; status: Literal["accepted","review","unmapped"]
FindingKind = Literal["changed","missing_in_new","added_in_new","status_changed","list_length_changed","type_changed","declared_type_changed","moved","renamed","dropped"]
class Finding(BaseModel): id: str; endpoint: str; new_endpoint: str | None; path: str; kind: FindingKind; source: Literal["diff","types","mapping"]; samples: list[Sample]; differing: int; type_info: dict[str, str] = {}; label: Literal["intended","regression","unsure"] | None = None; p: float | None = None; probabilities: dict[str, float] = {}; status: Literal["accepted","shown","unsure","error"] | None = None; reason: str | None = None
class Noise(BaseModel): endpoint: str; path: str; rule: str
class Score(BaseModel): correct: int; total: int; unsure: int; false_regressions: int; details: list[dict[str, Any]]
class Telemetry(BaseModel): llm_calls: int = 0; rule_decisions: int = 0; reasons: int = 0; retries: int = 0; seconds: float = 0; prompt_tokens: int = 0; cached_tokens: int = 0; completion_tokens: int = 0; cost_usd: float = 0
class Run(BaseModel): id: str; started_at: datetime; config: dict[str, Any]; endpoints: list[EndpointMap]; fields: list[FieldMap]; findings: list[Finding]; noise: list[Noise]; errors: list[Finding]; score: Score | None; telemetry: Telemetry
class AnswerKey(BaseModel): mapping: list[dict[str, Any]]; findings: list[dict[str, Any]]
```
`store.save(run, dir="runs") -> Path`, `store.load(run_id, dir="runs") -> Run`, `store.list_runs(dir="runs") -> list[Run]` (newest first).

- [ ] Test `test_round_trip`: build a `Run` with one finding whose sample bodies hold `10.01`, `10.0`, `10.005`; save; load; assert equal and the floats unchanged (Review focus 3).
- [ ] Test `test_list_runs_newest_first`.
- [ ] Run, expect failures (`ModuleNotFoundError`), implement, run, expect pass. Use `yaml.safe_dump(run.model_dump(mode="json"), sort_keys=False)`.
- [ ] Commit `feat: run models and yaml store`.

### Task 2: Toy services, fixtures

**Files:** Create `app/toys/data.py`, `app/toys/v1.py`, `app/toys/v2.py`, `app/main.py`, `fixtures/intent.md`, `fixtures/seeds.yaml`, `fixtures/answer_key.yaml`, `config/noise.yaml`, `tests/test_toys.py`.

**Produces:** `app.main.app` with sub-apps mounted at `/v1` and `/v2`, each serving `/openapi.json`. Pydantic `response_model`s on every route (declared types come from these).

Data: customers 1 (person, ZAR), 2 (business, ZAR); orders 1–5, page size 3; order 2 has items summing to 10.005.

| # | v1 | v2 |
|---|---|---|
| 1 | `GET /orders?page=` → `{page, items}` sorted by id | items reversed |
| 2 | `POST /orders` → `id` `ord_<uuid4>`, `createdAt` now | same, new values each call |
| 3 | `POST /orders` → 200 | 201 |
| 4 | `GET /customers/{id}` → `fullName` | `GET /clients/{clientId}` → `name` |
| 5 | `legacyCode` present | absent |
| 6 | `total` via `Decimal.quantize(ROUND_HALF_UP)` → 10.01 | `round(float, 2)` → 10.0 |
| 7 | pages = ceil(5/3) = 2 | pages = 5 // 3 = 1, so page 2 returns `items: []` |
| 8 | `currency: str` required | `currency: str \| None = None`; omitted for business |
| 9 | 404 `{"detail": "Order not found"}` | 404 `{"detail": "No order with id 999"}` |
| 10 | path `/customers/{id}` | path `/clients/{clientId}` |

Customer 404 messages are identical on both sides (no extra finding).

`fixtures/seeds.yaml`: `params: {id: [1, 2, 999], page: [1, 2]}`, `bodies: {"POST /orders": [{customerId: 1, items: [{sku: A1, qty: 2, unit: 5.0}]}, {customerId: 2, items: [{sku: B2, qty: 1, unit: 3.0}]}]}`.

`config/noise.yaml`: `mask: ["$.id", "$.createdAt"]` scoped to `POST /orders`; `unordered: [{endpoint: "GET /orders", path: "$.items", key: id}]`; patterns: ISO-8601 timestamps, `ord_` + uuid.

`fixtures/answer_key.yaml` (paths as the finding paths in Task 7):
```yaml
mapping:
  - {old: "GET /customers/{id}", new: "GET /clients/{clientId}"}
  - {endpoint: "GET /customers/{id}", old_field: fullName, new_field: name}
  - {endpoint: "GET /customers/{id}", old_field: legacyCode, new_field: null}
findings:
  - {n: 1,  endpoint: "GET /orders",          path: "$.items",      expect: noise}
  - {n: 2,  endpoint: "POST /orders",         path: "$.id",         expect: noise}
  - {n: 3,  endpoint: "POST /orders",         path: "status",       expect: intended}
  - {n: 4,  endpoint: "GET /customers/{id}",  path: "$.fullName",   expect: intended}
  - {n: 5,  endpoint: "GET /customers/{id}",  path: "$.legacyCode", expect: intended}
  - {n: 6,  endpoint: "GET /orders/{id}",     path: "$.total",      expect: regression}
  - {n: 7,  endpoint: "GET /orders",          path: "$.items",      expect: regression}
  - {n: 8,  endpoint: "GET /customers/{id}",  path: "$.currency",   expect: regression}
  - {n: 9,  endpoint: "GET /orders/{id}",     path: "$.detail",     expect: unsure}
  - {n: 10, endpoint: "GET /customers/{id}",  path: "endpoint",     expect: intended}
```
`fixtures/intent.md`: the intent note from the build spec, verbatim.

- [ ] Tests (TestClient): one per row above, asserting the exact v1/v2 values (e.g. `GET /v1/orders/2` total `10.01`, `GET /v2/orders/2` total `10.0`; `GET /v2/orders?page=2` items `[]`; `GET /v2/clients/2` has no `currency`). Plus `/v1/openapi.json` and `/v2/openapi.json` return 200 and list the expected paths.
- [ ] Run, fail, implement, pass. Gerdi also: `poetry run uvicorn app.main:app --reload`, open `/v1/docs` and `/v2/docs`.
- [ ] Commit `feat: toy v1/v2 services and fixtures`.

### Task 3: OpenAPI reader and request generation

**Files:** Create `nparity/openapi.py`, `nparity/config.py`, `nparity/generate.py`, `tests/test_generate.py`.

**Consumes:** Task 2 app. **Produces:**
```python
@dataclass class Endpoint: method: str; path: str; params: list[str]; response_schema: dict | None   # resolved $refs, 2xx
def load_spec(client: httpx.Client, base_url: str) -> dict
def endpoints(spec: dict) -> list[Endpoint]          # key "METHOD /path"
def generate(eps: list[Endpoint], seeds: Seeds, cap: int = 5) -> list[Request]
```
- [ ] Tests: v1 spec yields exactly `GET /orders`, `POST /orders`, `GET /orders/{id}`, `GET /customers/{id}`; `generate` gives `GET /orders/{id}` × ids `[1,2,999]`, `GET /orders` × pages `[1,2]`, two POST bodies; every endpoint has ≥1 request and ≤`cap`; a param with no seed is skipped with the endpoint still present only if it has no required params missing.
- [ ] Run, fail, implement, pass. Commit `feat: request generation from openapi and seeds`.

### Task 4: Evaluator base, FakeBackend, cache

**Files:** Create `nparity/evaluator/base.py`, `fake.py`, `cache.py`, `tests/test_evaluator.py`.

**Produces** (evaluator spec §2, trimmed):
```python
class Choice(BaseModel): id: str; instructions: str; criteria: dict[str, str]   # key -> description
class Answer(BaseModel): value: str; probabilities: dict[str, float]; p_winner: float; confidence: float; unseen_mass: float = 0; censored: bool = False; off_list: bool = False; reason: str | None = None; meta: dict[str, Any] = {}
class Backend(Protocol):
    id: str
    max_options: int
    def evaluate(self, state: str | dict, questions: list[Choice], reasons: bool = False) -> dict[str, Answer]: ...
def build(name: str | None = None) -> Backend     # NPARITY_LLM, default "fake"; wraps in Cached
```
Question id conventions (Fake relies on them): `map:endpoint:<old>`, `map:field:<endpoint>:<old_field>`, `triage:<endpoint>:<path>`. FakeBackend answers one-hot from `AnswerKey` (mapping new endpoint/field, or `none` for null; triage `expect`), and uniform over criteria with `off_list: true` for unknown ids. Reason: `"fake: from answer key"`.
Cache key: sha256 of (backend id, profile id+version, template version, canonical JSON state, question JSON); file `cache/<key>.yaml`.

- [ ] Tests: Fake returns `GET /clients/{clientId}` with p 1.0 for `map:endpoint:GET /customers/{id}`; unknown id is uniform + off_list; `Cached` calls the inner backend once for two identical evaluates and again after the question text changes.
- [ ] Run, fail, implement, pass. Commit `feat: evaluator interface, fake backend, yaml cache`.

### Task 5: Mapping

**Files:** Create `nparity/map.py`, `config/thresholds.yaml`, `tests/test_map.py`.

**Consumes:** Task 3 `Endpoint`, Task 4 `Backend`. **Produces:**
```python
def map_endpoints(old: list[Endpoint], new: list[Endpoint], ev: Backend, th: Thresholds) -> list[EndpointMap]
def map_fields(pairs: list[tuple[Endpoint, Endpoint]], ev: Backend, th: Thresholds) -> list[FieldMap]
def status_for(p: float | None, censored: bool, t: Threshold) -> Literal["accepted","review","unmapped"]
```
Rules per design §2: same method → path-token stem match (singularise, lowercase) + same path-param count → one left = `rule`; several = one `Choice` with all + `none`; none left = widen to same method, one `Choice`. Fields: top-level response properties; exact name = `rule`; leftovers each one `Choice` over leftover new fields + `none` (→ `new: None`). Thresholds `config/thresholds.yaml` as evaluator spec §6 (mapping 0.95/0.50, triage_intended 0.98/0.50, regression never auto). Tournament (> 30) is Task 12; until then raise `TooManyOptions`.

- [ ] Tests (with Fake): orders endpoints map by rule; `GET /customers/{id}` → `GET /clients/{clientId}` via llm, accepted; fields `id,email,type,currency` by rule, `fullName→name` llm, `legacyCode→None` llm; `status_for(0.96, False, mapping)` accepted, `(0.6, …)` review, `(0.3, …)` unmapped, `(0.99, True, …)` review. A stub backend asserting the widened `Choice` contains `none` and every v2 GET endpoint.
- [ ] Run, fail, implement, pass. Commit `feat: rule-first endpoint and field mapping`.

### Task 6: Retry and replay

**Files:** Create `nparity/retry.py`, `nparity/replay.py`, `tests/test_retry.py`, `tests/test_replay.py`.

**Produces:**
```python
@dataclass class RetryPolicy: attempts: int = 4; base: float = 0.5; cap: float = 8.0; statuses: frozenset[int] = {408,429,500,502,503,504,529}
class RetryExhausted(Exception): attempts: int; last: Exception
def is_retryable(exc: Exception, policy: RetryPolicy) -> bool     # HTTPStatusError in statuses, TimeoutException, TransportError
def retry_call(fn: Callable[[], T], policy: RetryPolicy, *, sleep=time.sleep, rand=random.random, on_retry=None) -> T
def replay(reqs: list[Request], emap: dict[str, EndpointMap], fmap: list[FieldMap], client: httpx.Client, old_base: str, new_base: str, policy: RetryPolicy, workers: int = 8) -> tuple[list[Sample], int]   # (samples, retries)
```
Backoff: `sleep(rand() * min(cap, base * 2**attempt))`. Replay: map path template and path params by position, fill, send both with `retry_call`; HTTP 4xx/5xx from the toy are *results*, not errors (only raise for retry inside the call when the status is retryable). Exhausted → `HttpResult(status=None, error=str)`. Unmapped endpoints: old only, new `error="unmapped"`.

- [ ] Retry tests: fails twice with `ConnectError` then succeeds → result, 2 sleeps, each ≤ cap; 400 → raised immediately, 0 sleeps; always 503 → `RetryExhausted` after 4 attempts.
- [ ] Replay tests (TestClient as `client`, bases `http://testserver/v1` and `/v2`): `GET /customers/{id}` id 2 goes to `/v2/clients/2`; 999 on orders gives two 404 results, not errors; a transport that always raises gives `error` results and the other samples are intact.
- [ ] Run, fail, implement, pass. Commit `feat: per-call retry and replay`.

### Task 7: Normalise, diff, type checks, findings

**Files:** Create `nparity/normalise.py`, `nparity/diff.py`, `nparity/types.py`, `nparity/findings.py`, `tests/test_normalise.py`, `tests/test_diff.py`, `tests/test_types.py`, `tests/test_findings.py`.

**Produces:**
```python
def normalise(endpoint: str, old: HttpResult, new: HttpResult, rules: NoiseRules, renames: dict[str, str]) -> tuple[HttpResult, HttpResult, list[Noise]]
@dataclass class Diff: path: str; kind: FindingKind; old: Any; new: Any
def diff(old: HttpResult, new: HttpResult) -> list[Diff]          # status -> path "status"; lists of different length -> list_length_changed at the list path, no per-element diffs
def observed_types(samples: list[Sample]) -> dict[str, tuple[set[str], set[str]]]   # path -> (old types, new types); "decimal(2)" style for floats
def declared_diffs(old_schema: dict, new_schema: dict, fmap: list[FieldMap]) -> list[Diff]   # kind declared_type_changed; type/format/required/nullable/enum
def build_findings(endpoint_pairs, samples, fmap, emap, noise_rules, schemas) -> tuple[list[Finding], list[Noise], list[Finding]]   # findings, noise, errors
```
Grouping key `(endpoint, path, kind)`; `differing` = samples where it occurs. Declared diffs on a path that already has a finding attach to its `type_info`, else become their own finding. Mapping findings: `moved` (path `endpoint`) for any endpoint whose new path differs; `renamed` (path `$.<old>`) and `dropped` (path `$.<old>`) for accepted LLM field maps. Finding ids `f-001…` in a stable order (endpoint, path). Noise recorded only when a rule actually changed the value.

- [ ] Normalise tests: masks `$.id`/`$.createdAt` on POST and records noise; sorting `$.items` by `id` makes page 1 equal and records noise; rename `fullName→name` applied to old body.
- [ ] Review focus 1: after normalise + diff for customer 1 there is **no** `$.fullName`/`$.name` value diff, and `build_findings` emits exactly one `renamed` finding for `$.fullName`.
- [ ] Review focus 2: page 2 still yields `list_length_changed` at `$.items` (old 2, new 0) after sorting.
- [ ] Diff tests: `$.total` 10.01 vs 10.0 → `changed`; 200 vs 201 → `status_changed` at `status`; `$.currency` absent → `missing_in_new`.
- [ ] Types tests: declared `currency` string required → string nullable optional produces `declared_type_changed`, attached to the `$.currency` finding's `type_info`.
- [ ] End-of-task check with Fake mapping on the toys: findings are exactly answer-key items 3–10 (8 findings), noise covers items 1–2, errors empty.
- [ ] Run, fail, implement, pass. Commit `feat: normalise, diff, type checks, findings`.

### Task 8: Triage and scoring

**Files:** Create `nparity/triage.py`, `nparity/score.py`, `tests/test_triage.py`, `tests/test_score.py`.

**Produces:**
```python
def triage(findings: list[Finding], intent: str, ev: Backend, th: Thresholds) -> list[Finding]
def score(run: Run, key: AnswerKey) -> Score
```
One `Choice` per finding, id `triage:<endpoint>:<path>`, criteria `intended` / `regression` / `unsure` with one-line descriptions; state = `{intent, finding: {endpoint, new_endpoint, path, kind, examples (≤3 samples, old/new values only), type_info}}`. Status: `regression` → `shown` always; `intended` with p ≥ 0.98 → `accepted`, else label `unsure`, status `unsure`; `unsure` → `unsure`. Reasons requested only for shown/unsure. Score: `expect: noise` keys match only `Noise` entries, all other keys match only findings, both on `(endpoint, path)` exactly (items 1 and 7 share `GET /orders` + `$.items`; this split is what keeps them apart); label must equal `expect`; `total` counts answer-key findings only (mapping entries feed Fake); `false_regressions` = regression labels on keys expecting non-regression.

- [ ] Triage tests (Fake + a stub returning intended 0.62): 0.62 intended → `unsure`; regression at p 0.4 → still `shown`; reasons requested only for shown/unsure.
- [ ] Review focus 4: key path `$.items` matches a finding at `$.items` and not one at `$.items[0].id`; noise key `$.id` matches `Noise(path="$.id")`.
- [ ] Run, fail, implement, pass. Commit `feat: triage and answer-key scoring`.

### Task 9: Pipeline and CLI (skeleton complete)

**Files:** Create `nparity/pipeline.py`, `nparity/cli.py`, `tests/test_e2e.py`, `tests/test_cli.py`. Modify `pyproject.toml` (script entry `nparity = "nparity.cli:app"` if Poetry allows with `package-mode = false`; otherwise `poetry run python -m nparity.cli`).

**Produces:**
```python
@dataclass class RunConfig: old: str; new: str; intent: Path; seeds: Path; answer_key: Path | None; backend: str = "fake"
def run(cfg: RunConfig, client: httpx.Client, ev: Backend | None = None) -> Run
```
CLI: `run --old --new --intent [--seeds] [--answer-key] [--backend]` → saves, prints counts / regressions / unsure / score / telemetry line / `http://localhost:8000/runs/<id>`; `show RUN_ID`; `runs`.

- [ ] E2E test (TestClient, Fake): score `10/10`, `false_regressions == 0`, three `shown` regressions (items 6, 7, 8), one `unsure` (item 9), telemetry `rule_decisions > llm_calls`.
- [ ] Review focus 5: a client whose transport raises `ConnectError` for `/v2/orders/1` only → one `error` finding, every other expected finding still present.
- [ ] CLI test with Typer `CliRunner` against a pre-saved run: `show` prints `Regressions: 3`.
- [ ] Gerdi: `uvicorn` in one terminal, `nparity run --old http://localhost:8000/v1 --new http://localhost:8000/v2 --intent fixtures/intent.md --answer-key fixtures/answer_key.yaml`. Expect the summary and a file in `runs/`.
- [ ] Commit `feat: pipeline and cli, walking skeleton end to end`.

### Task 10: Web UI

**Files:** Create `app/web/routes.py`, `app/web/templates/{base,runs,run,finding,mapping}.html`, `app/web/static/nparity.css`, `tests/test_web.py`. Modify `app/main.py` (mount router, static).

**Consumes:** `store.list_runs`, `store.load`. Layout and copy from `docs/mockups/web-ui.html` (CSS moved verbatim into `nparity.css`; drop the mock banner and hash-switching script).

Routes: `GET /` runs list; `GET /runs/{id}`; `GET /runs/{id}/findings/{fid}` partial (HTMX `hx-get` on row expand, `hx-target` the row body); `GET /runs/{id}/mapping`. The side-by-side panes highlight the line containing the finding's key; p bar threshold tick from thresholds by label.

- [ ] Tests (TestClient + a run saved to a tmp dir, dir injected via app state): `/` lists the run id; run page contains `Regressions`, `10/10`, `$.total`; partial contains `10.01` and `10.0`; mapping page contains `GET /clients/{clientId}` and `llm`; unknown run → 404.
- [ ] Gerdi: open `http://localhost:8000/` after a CLI run; compare with the mockup.
- [ ] Commit `feat: web ui for saved runs`.

### Task 11: Flash backend

**Files:** Create `nparity/evaluator/logprob_chat.py`, `nparity/evaluator/profiles.py`, `config/profiles/flash.yaml`, `tests/test_logprob_chat.py`, `tests/test_live_flash.py`.

**Produces:**
```python
def codes_for(k: int) -> list[str]                                     # A..Z for k <= 26, else 01..k
def parse_top_logprobs(resp: dict, codes: list[str]) -> tuple[dict[str, float], float, bool]   # raw p per seen code, unseen_mass, off_list
class LogprobChatBackend:  # implements Backend; id "logprob_chat:<profile.id>@<version>"; max_options from profile
```
Profile YAML exactly as evaluator spec §3. Prompt template v1 from evaluator spec §5. Per-question calls in a thread pool (`concurrency`), each through `retry_call`. Answer: `probabilities` = seen raw p renormalised (display), `p_winner` = winner's **raw** p, `censored` = unseen_mass > 0.05. Reasons: second call per evaluator spec §4.11. Telemetry from `usage` and the `fireworks-cached-prompt-tokens` header.

- [ ] Unit tests on `proto/raw/E4_1.json`: `A` raw p ≈ 0.998867 (abs 1e-6), `D` unseen, `unseen_mass` ≈ 1 − sum of the 5 visible raw p (includes `Let`), not censored, winner `A`. A synthetic response with only non-code tokens → `off_list`. Tokens `" A"` and `"A."` normalise to `A`. `codes_for(30)[0] == "01"`.
- [ ] Unit test with a fake transport: request body has `reasoning_effort: "none"`, `max_tokens: 1`, `top_logprobs: 5`, `temperature: 0`; a 503 then 200 is retried.
- [ ] Live tests (`@pytest.mark.live`): E4 question → p(A) > 0.95; toy mapping `GET /customers/{id}` → `/clients/{clientId}`; one triage smoke (item 6 regression, item 3 intended).
- [ ] Gerdi: `FIREWORKS_API_KEY=… poetry run pytest -m live -v`, then a CLI run with `--backend flash`; report the score and any finding that lands above a threshold wrongly.
- [ ] Commit `feat: fireworks flash logprob backend`.

### Task 12: Tournament mapping and probe (only if ahead)

**Files:** Modify `nparity/map.py`, `proto/logprobs_test.py`. Test `tests/test_map.py`.

- [ ] Tests (stub backend): 70 candidates → 3 batches of ≤30 each with `none`, final round without `none` over ≤9 finalists, `source: llm_tournament`; final winner that didn't win its batch at ≥0.95 → `review`; all batches won by `none` → `unmapped`.
- [ ] Implement in `map.py`, replacing `TooManyOptions`.
- [ ] Add `E16` to `proto/logprobs_test.py`: the E8 30-option set split into 3 batches of 10, top 3 each, final round of 9 without `None of these`, 3 shuffles; record p(correct) per round to `results.json`.
- [ ] Gerdi: `poetry run python proto/logprobs_test.py --exp E16`; report numbers. Add a short §3.4 to `logprobs_report.md`.
- [ ] Commit `feat: guarded tournament mapping for long candidate lists`.

### Task 13: Freeze the demo run

- [ ] Gerdi: Flash CLI run with a warm cache; rename to `runs/demo.yaml`; commit it and the `cache/` files it used (force-add).
- [ ] Rerun with the frozen cache: identical findings and score, `llm_calls` served from cache.
- [ ] Commit `chore: frozen demo run`.

## Self-review

- Spec coverage: generate (3), map incl. tournament (5, 12), replay + retry (6), normalise/diff/types/grouping/mapping findings (7), triage + thresholds + score (8), Run YAML + CLI (1, 9), web incl. mapping page (10), Flash + Fake + cache (4, 11), tests key-free with live marker (0, 11). Deferred by spec: Jev, SampleVote, run button, ledger.
- Names checked across tasks: `Request`, `HttpResult`, `Sample`, `EndpointMap`, `FieldMap`, `Finding`, `Noise`, `Run`, `AnswerKey`, `Choice`, `Answer`, `Backend`, `RetryPolicy`, `retry_call`.
- Open risk: Poetry script entry with `package-mode = false` may not install; fallback `python -m nparity.cli` noted in Task 9.
