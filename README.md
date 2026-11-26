# nParity

**Will we break anything?** nParity sends the same requests to an old and a new HTTP service, maps old endpoints and fields to new ones, strips noise, diffs what's left, and triages every difference against a plain-language *intent note*: **intended**, **regression** or **unsure**, each with a probability a reviewer can act on. You read a handful of findings instead of a wall of diffs.

Built for SA PDE AI Skills Day (team Chai-GPT). Prototype, not product: no auth, no deployment, runs locally.

## Quick start

```bash
mise install                              # or: asdf install   (Python 3.14 from .tool-versions)
uv sync                                   # dependencies from uv.lock
uv run pytest -q                          # everything, offline, no key needed
uv run uvicorn app.main:app --reload      # toy services + web UI on http://localhost:8000
uv run python -m nparity.cli run --old http://localhost:8000/v1 --new http://localhost:8000/v2
```

The last command runs the toy comparison with the offline fake evaluator and should print `Answer key: 10/10 correct`. Open the URL it prints to see the report.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | **3.14.x** | pinned in `.tool-versions`; install via **mise or asdf** (either works) |
| uv | recent | primary dependency manager |
| Poetry | **2.x** (tested on 2.5.1) | supported fallback during the uv transition |
| `nexus` CLI | — | only for live runs on Fireworks; supplies `FIREWORKS_API_KEY` |

## Setup

### 1. Python 3.14

`.tool-versions` is read by both mise and asdf. Pick one, **don't run both**: they fight over `PATH`, and whichever shims come first win silently.

```bash
mise install && mise current        # expect: python 3.14.0
# or
asdf plugin add python https://github.com/asdf-community/asdf-python.git   # first time only
asdf install && asdf current
```

From inside the repo, `python --version` must print 3.14.x.

### 2. Dependencies

```bash
uv sync                    # creates .venv/ in the repo (gitignored) from uv.lock
uv sync --system-certs     # the same, behind a TLS-inspecting corporate proxy (or UV_NATIVE_TLS=1)
```

Poetry still works from the same `pyproject.toml`:

| uv | Poetry |
|---|---|
| `uv sync` | `poetry install` |
| `uv run X` | `poetry run X` |

Both lock files must pin the same versions, and both follow a 7-day dependency cooldown (`[tool.uv] exclude-newer = "7 days"`). `tests/test_project_config.py` fails if the locks drift. How to update a dependency safely: [`docs/decisions/0001-poetry-uv-cross-compatibility.md`](docs/decisions/0001-poetry-uv-cross-compatibility.md).

### 3. Fireworks key (live runs only)

Everything works offline with the fake evaluator. Live runs use DeepSeek Flash on Fireworks and need `FIREWORKS_API_KEY`.

**We never export the key and never paste it.** Pass it inline to the one command that needs it, straight from nexus:

```bash
FIREWORKS_API_KEY="$(nexus key export 2>/dev/null | head -n1)" <command>
```

- The key exists only in that one process's environment: not in your shell, not in shell history (only the command text is), not in the repo, and never on screen.
- `2>/dev/null | head -n1` drops nexus's update notice, which would otherwise end up inside the key.
- **Don't run `nexus key export` on its own**: it prints the key to your terminal. To check it works without revealing it: `nexus key export 2>/dev/null | head -n1 | cut -c1-3` should print `fw_`.
- Nothing in nParity prints or stores the key. Only `Authorization` headers carry it.

### 4. TLS behind a corporate proxy

HTTPS calls from Python (Fireworks, public APIs) verify against the **OS trust store** through `truststore`, so a corporate root CA in the macOS keychain just works. Verification is never turned off. If you still see `CERTIFICATE_VERIFY_FAILED`, check `truststore` is installed (`uv sync`).

## Running

### Tests

```bash
uv run pytest -q                                                                        # offline, deterministic, no key
FIREWORKS_API_KEY="$(nexus key export 2>/dev/null | head -n1)" uv run pytest -m live -v -s   # hits Fireworks (~$0.002)
```

Live tests skip themselves when the key isn't set. `-s` prints every finding with its label, probability and reason.

### Web UI

```bash
uv run uvicorn app.main:app --reload
```

To start **Flash** comparisons from the web form, give the server the key the same inline way:

```bash
FIREWORKS_API_KEY="$(nexus key export 2>/dev/null | head -n1)" uv run uvicorn app.main:app --reload
```

| Page | What it shows |
|---|---|
| `/` | Saved runs: backend, counts, answer-key score, time, cost |
| `/compare` | **New run** form. Presets: *Load toy demo*, *Load Petstore*. Sources can be an API base URL, a Swagger/OpenAPI spec (URL or local file) or a captured-response manifest. Live progress console. Starting runs only works from `localhost` |
| `/runs/{id}` | Report: counts, score, then regressions, unsure, intended, noise, errors. Expand a finding for both responses side by side, types, probability against its threshold, and the reason |
| `/runs/{id}/mapping` | Old to new endpoints and fields: rule or LLM, probability, status, runners-up, declared type changes |
| `/v1/*`, `/v2/*` | The toy services (`/v1/docs`, `/v2/docs` for Swagger UI) |

The app reads and writes `runs/` in the current directory, so start it from the repo root.

### CLI

All commands: `uv run python -m nparity.cli <command> --help`.

**Toy demo, offline** (server running):

```bash
uv run python -m nparity.cli run --old http://localhost:8000/v1 --new http://localhost:8000/v2
```

**Toy demo on Flash:**

```bash
FIREWORKS_API_KEY="$(nexus key export 2>/dev/null | head -n1)" uv run python -m nparity.cli run \
  --old http://localhost:8000/v1 --new http://localhost:8000/v2 --backend flash
```

Expect 10/10, 0 false regressions, 1 unsure, about 10 s and US$0.0015.

**Public API: Swagger Petstore v2 vs v3** (no server needed, GET only):

```bash
FIREWORKS_API_KEY="$(nexus key export 2>/dev/null | head -n1)" uv run python -m nparity.cli run \
  --old https://petstore.swagger.io/v2 \
  --new https://petstore3.swagger.io/api/v3 \
  --old-spec https://petstore.swagger.io/v2/swagger.json \
  --new-spec https://petstore3.swagger.io/api/v3/openapi.json \
  --seeds fixtures/petstore/seeds.yaml \
  --intent fixtures/petstore/intent.md \
  --no-score --backend flash --name petstore
```

The two Petstore servers hold different data (v2 is a shared junk sandbox), so expect many value differences. See [`samples/api-versions/README.md`](samples/api-versions/README.md).

**Captured responses, offline:** in the web form choose *JSON manifest* on both sides, e.g. `samples/api-versions/manifest.json#openfoodfacts_product`. Pairs: `petstore_spec`, `petstore_findByStatus`, `openfoodfacts_product`, `wikipedia_page`. Re-capture with `samples/api-versions/capture.sh`.

| Command | Does |
|---|---|
| `run` | Run a comparison, save it to `runs/`, print the summary and report URL |
| `show RUN_ID` | Print a saved run's summary |
| `runs` | List saved runs |
| `freeze RUN_ID [--as demo]` | Save a copy under a fixed id for the demo page |

Useful `run` options: `--old-spec/--new-spec` (URL or file, default `<base>/openapi.json`), `--seeds`, `--intent`, `--answer-key`, `--no-score`, `--backend fake|flash` (or `NPARITY_LLM`), `--name`, `--runs-dir`.

#### CLI automation

Use `--format json` before or after the command name. Successful commands write one JSON document to stdout. Errors and optional progress go to stderr. Text is the default.

- Add `--dry-run` to `run` to see planned calls, seed sources and skipped endpoints. The plan can fetch remote specs. Replay, discovery and model calls are skipped.
- Add `--compact` to `run` or `show` for counts, coverage, cost and finding keys. On `show`, use `--status regression`, `--endpoint 'GET /orders'`, `--limit` and `--offset` to narrow results. Fetch one finding and its response samples with `finding RUN_ID FINDING_ID_OR_KEY --format json`.
- Add `--progress jsonl` to stream progress events on stderr. The first event includes the run ID. Use `--detach` to start a background run and return its ID immediately. Poll with `status RUN_ID --after 0 --wait 10 --format json`, passing the last event's `seq` as `--after` on the next call. Use the same `--runs-dir` if you set a custom one.
- Add `--fail-on regression`, `--fail-on unsure` or `--fail-on error` to gate the saved result. You can repeat the flag. The regression gate uses the run's regression findings.

| Exit code | Meaning |
|---|---|
| 0 | Command completed |
| 2 | Invalid input or missing file |
| 3 | Retryable upstream failure |
| 4 | Permanent or unexpected failure |
| 5 | Run completed and saved, with a requested gate triggered |
| 130 | Interrupted |

For detached runs, `status` returns the run's outcome in `exit_code` once it finishes. The polling command itself succeeds when it can read the status.

### Freezing the demo

Flash answers jitter slightly between runs. The cache makes the demo repeatable, free and offline.

```bash
rm -rf cache/                                      # start clean so the cache holds only the demo's answers
FIREWORKS_API_KEY="$(nexus key export 2>/dev/null | head -n1)" uv run python -m nparity.cli run \
  --old http://localhost:8000/v1 --new http://localhost:8000/v2 --backend flash          # live, fills cache/
FIREWORKS_API_KEY="$(nexus key export 2>/dev/null | head -n1)" uv run python -m nparity.cli run \
  --old http://localhost:8000/v1 --new http://localhost:8000/v2 --backend flash          # from cache: same result, $0
uv run python -m nparity.cli freeze <run-id-from-the-second-run>
git add -f runs/demo.yaml cache/
```

Then open `http://localhost:8000/runs/demo`. `runs/demo.yaml` alone is enough to show the report; `cache/` is what lets you re-run it identically without Fireworks.

## Comparing your own services

You need:

1. **Two base URLs**, old and new.
2. **An OpenAPI 3 or Swagger 2.0 spec** for each side enables contract checks and request generation. Serve the specs at `<base>/openapi.json` or pass them with `--old-spec/--new-spec`.
3. **An optional seeds file** overrides generated values for parameters and request bodies. Use IDs that exist on both sides. Replay defaults to GET. Add other methods explicitly to `methods:` to enable them.
   ```yaml
   methods: [GET]
   params:
     id: [1, 2, 999]      # 999 = a not-found case
     page: [1, 2]
   bodies:
     "POST /orders":
       - {customerId: 1, items: [{sku: A1, qty: 2, unit: 5.0}]}
   ```
4. **An intent note** (Markdown): what the rewrite is meant to change, as an explicit list, ending with "Nothing else should change". Be unambiguous: a vague sentence gets a vague (unsure) answer, which is the point.
5. **Auth headers**, if the services need them: `Name: env:VAR` per side, never a literal value. In the web form: the *Headers* box on each side. On the CLI: `--old-header "Authorization: env:OLD_TOKEN" --new-header "Authorization: env:NEW_TOKEN"`. Pass the variables inline, as with the Fireworks key, so they only exist for that one process:
   ```bash
   OLD_TOKEN="$(…your secret command…)" NEW_TOKEN="$(…)" uv run uvicorn app.main:app --reload
   ```
   Runs and configurations store header **names** only. A missing variable fails the run before any request, naming the variable.
6. Optional: **noise rules** (`config/noise.yaml`: masked paths, unordered lists) and an **answer key** to score against.

### Seed generation and coverage

Generate a seeds file from a spec with `uv run python -m nparity.cli seeds openapi.yaml --out generated-seeds.yaml`. Each generated value includes its source. Pass `--manual seeds.yaml` to preserve your overrides.

Use `--samples` with the `seeds` command, or `--seed-samples` with `run`, to supply a curl file, Postman collection, capture manifest, or request pairs. The importer reads these files locally. Use `--discover-from 'GET /pets'` with `run` to fetch seeds from an explicitly allowed endpoint on the old API. Repeat the option for each endpoint. Discovery skips runs that use custom headers on the old API.

The report lists coverage per endpoint, including request seed sources and reasons a sample did not count. Declared differences have their own section. Use `--contract-only` or **Compare specs only** in the web form to skip endpoint replay.

### Basic checks without specs

Use **Endpoint URL (no spec)** on both sides to compare two GET responses, or supply a YAML or JSON file of paired GET requests. Basic checks compare status codes, JSON keys and value types. The report states how many endpoints provided usable responses.

```yaml
requests:
  - old: {method: GET, path: /cats/42}
    new: {method: GET, path: /pets/42}
```

Set the two API base URLs and select **Sample requests file** in the web form, or pass `--samples samples.yaml` to `nparity.cli run`. Put query values in each request's optional `params` map.

## How it works

1. **Generate** requests from the old spec crossed with the seeds (up to 5 per endpoint).
2. **Map** old to new. Rules first (same method, matching path words, same path-param count; exact field names). Only what the rules can't settle goes to the LLM, asked once with the full candidate list.
3. **Replay** each request against old and its mapped counterpart against new, with per-call retry (exponential backoff with jitter, 4 attempts).
4. **Normalise** noise: explicit masks, accepted renames, and by default per-call datetimes, dates, UUIDs and epoch timestamps are replaced by their *format* (`<datetime tz=Z precision=s>`), so a value that differs per call is noise but a change of format, timezone or type is still a finding. Lists of objects with a stable key (`id`, `uuid`, `key`, `code`) are matched by key: paths like `$.items[id=10].name`, and items only on one side become one *items removed* / *items added* finding. Then **diff** deterministically and check observed and declared **types**. Numbers, rounding, counts and pagination are caught here, never by the LLM.
5. **Triage** each finding against the intent note: one 1-token question, answer read from logprobs. Intended needs p ≥ 0.98, regression needs p ≥ 0.999; anything below its bar becomes **unsure** and goes to a human. Nothing is auto-dismissed.
6. **Report**: a `Run` saved as YAML in `runs/`, rendered by the CLI and the web UI. Scored against the answer key when one is given.

Thresholds: `config/thresholds.yaml`. Model profile: `config/profiles/flash.yaml`.

## What's in the repo

```
nparity/            the engine: generate, map, replay, normalise, diff, types, findings, triage, score, cli
  evaluator/        Jev-shaped LLM layer: Flash (logprobs), fake (answer key), YAML cache
app/                FastAPI: toy services (/v1, /v2) and the web UI
config/             thresholds, noise rules, model profiles
fixtures/           toy intent note, seeds, answer key; petstore/ for the public-API run
samples/            captured old/new responses from public APIs + manifest
runs/               saved runs (gitignored, except runs/demo.yaml)
cache/              cached LLM answers, one YAML per question (gitignored; force-add for the demo)
tests/              pytest; test_live_flash.py is the only one that needs a key
docs/               design, plan, specs, logprobs report, PRDs, decisions, pitch, mockup
issues/             open UX and tooling issues
proto/              the original logprobs probe (16 experiments)
```

Key docs: [`docs/nparity-design.md`](docs/nparity-design.md) (approved design), [`docs/nparity-plan.md`](docs/nparity-plan.md) (implementation plan), [`docs/nparity-evaluator-spec.md`](docs/nparity-evaluator-spec.md) (LLM layer), [`docs/logprobs_report.md`](docs/logprobs_report.md) (what Flash can and can't do, measured), [`docs/problem-definition.md`](docs/problem-definition.md), [`docs/pitch/nparity-pitch.html`](docs/pitch/nparity-pitch.html), [`docs/prd/`](docs/prd/).

## Logprobs probe

The experiments behind the LLM design. Needs the key:

```bash
FIREWORKS_API_KEY="$(nexus key export 2>/dev/null | head -n1)" uv run python proto/logprobs_test.py            # all 16, ~30 s, ~$0.005
FIREWORKS_API_KEY="$(nexus key export 2>/dev/null | head -n1)" uv run python proto/logprobs_test.py --exp E4 E7
```

Writes `proto/raw/<EXP>_<n>.json` and `proto/results.json`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `CERTIFICATE_VERIFY_FAILED` on a live run | `uv sync` so `truststore` is installed; it verifies against the macOS keychain |
| `uv sync` / `uv run` fails with `invalid peer certificate: UnknownIssuer` | Corporate TLS proxy: add `--system-certs` (`uv run --system-certs pytest -q`) or `export UV_NATIVE_TLS=1` for the session. Only needed while uv downloads packages |
| Live tests say `SKIPPED (FIREWORKS_API_KEY not set)` | The key didn't reach the process. Use the inline form exactly as above; `nexus key export` takes no arguments |
| Flash answers come back as `LLM error: ...` / every triage is unsure | Fireworks unreachable or the key is wrong. The run still completes; errors are marked, not hidden |
| Web form: "Set FIREWORKS_API_KEY in the server environment" | Start `uvicorn` with the inline key (see Web UI) |
| Web form: "Open nParity on localhost" (403) | Starting runs is limited to `localhost`; open `http://localhost:8000/compare` |
| Report link from the CLI is 404 | `uvicorn` was started from another directory; start it from the repo root |
| Run finds `No requests generated` | The seeds don't cover a required parameter or request body; add them |
| `mise ERROR No version is set for python` | You're outside the repo. `cd` in, or `mise use -g python@3.14.0` |
| `asdf: No preset version installed for command python` | `asdf install` in the repo root |
| uv used the wrong Python | `uv sync --python "$(mise which python)"` (or `asdf where python`) |
| Wrong Python in a fresh shell | Both mise and asdf are active; disable one |

## Licence

MIT. See `LICENSE`.

## Notes

- `.tool-versions` (`python 3.14.0`) and `requires-python` (`>=3.14`) stay in sync; bump both together.
- `docs/logprobs_report.md` records its results as run in the original session (Python 3.12.10, 66 calls). Findings are version-independent.
