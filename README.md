# aiskillsday

Probing `logprobs` behaviour of DeepSeek Flash on Fireworks AI (OpenAI-compatible API,
custom `base_url`). Results feed the nParity evaluator specs in `docs/`.

## Layout

```
.
├── .tool-versions          python 3.14.0 — read by mise AND asdf
├── pyproject.toml          deps + requires-python >=3.14 (uv + poetry, no package)
├── uv.lock                 locked dependency set (uv) — commit this
├── poetry.lock             kept during the uv transition
├── proto/
│   ├── logprobs_test.py    the one script: 16 experiments (E0–E15)
│   ├── raw/                57 raw API responses, one file per recorded call
│   └── results.json        machine-readable summary of every experiment
└── docs/                   specs + writeup (build, evaluator, llm layer, results report)
```

**`pyproject.toml` + `uv.lock` are the source of truth** for dependencies.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | **3.14.x** | pinned in `.tool-versions`; install via **mise or asdf** (either works) |
| uv | recent | manages the virtualenv + dependencies |
| Poetry | **2.x** (tested on 2.5.1) | supported fallback |
| Fireworks key | — | `FIREWORKS_API_KEY`, never committed |

## Setup

### 1. Python 3.14 via your version manager

`.tool-versions` is read natively by both mise and asdf, so use whichever you already have.
Pick one — **don't run both**, they fight over `PATH` (whichever's shims come first wins,
silently).

**mise:**

```bash
mise install            # installs python 3.14.0 from .tool-versions
mise current            # expect: python 3.14.0
```

**asdf:**

```bash
asdf plugin add python https://github.com/asdf-community/asdf-python.git   # first time only
asdf install            # installs python 3.14.0 from .tool-versions
asdf current            # expect: python 3.14.0 ... .tool-versions
```

Sanity check from inside the repo — this must print 3.14.x:

```bash
python --version
```

### 2. Dependencies via uv

```bash
uv sync
```

That's it. uv resolves Python from `PATH` (so it picks up the mise/asdf 3.14), creates
a `.venv/` in the project (gitignored) and installs dependencies from `uv.lock`.

`[tool.uv] package = false` (and `package-mode = false` for Poetry) in `pyproject.toml` is
deliberate: there is no importable `aiskillsday` package, so the project itself must not
be built/installed.

**7-day dependency cooldown.** `[tool.uv] exclude-newer = "7 days"` makes uv ignore releases
newer than 7 days (the same rule as the machine-wide `/etc/uv/uv.toml`). Both lock files must
pin the same versions, so Poetry is held to the cooldown too: after `uv lock`, align Poetry by
temporarily pinning the differing packages to the `uv.lock` versions, run `poetry lock`, restore
`pyproject.toml`, and run `poetry lock` again. `tests/test_project_config.py` fails if the two
locks drift.

`exclude-newer` is a relative duration, so a fresh `uv lock` on a later day can resolve newer
versions. The committed `uv.lock` is the source of truth; regenerate it deliberately.

Poetry equivalents (Poetry 2.x still works):

| uv | Poetry |
|---|---|
| `uv sync` | `poetry install` |
| `uv run X` | `poetry run X` |

### 3. API key

```bash
export FIREWORKS_API_KEY=...        # never commit, never hardcode
```

Shell-profile export or a secret manager both fine — the script only reads the env var.

## Running

```bash
uv run python proto/logprobs_test.py                      # all 16 experiments, ~30 s, ~$0.005
uv run python proto/logprobs_test.py --exp E4 E7          # subset
uv run python proto/logprobs_test.py --model <fireworks-model-id>
```

Writes to its own directory: `proto/raw/<EXP>_<n>.json` and `proto/results.json`
(both regenerated per run — `raw/` keeps one file per recorded call).

## Running nParity

```bash
uv run pytest -q                                   # everything, key-free (FakeBackend)
uv run pytest -m live -v                           # Fireworks checks, needs FIREWORKS_API_KEY
uv run uvicorn app.main:app --reload               # toys at /v1 and /v2, web UI at /
```

Design and plan: `docs/nparity-design.md`, `docs/nparity-plan.md`. UI mockup: `docs/mockups/web-ui.html`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `mise ERROR No version is set for python` | You're outside the repo (no `.tool-versions` applies). `cd` in, or set a default: `mise use -g python@3.14.0` |
| `asdf: No preset version installed for command python` | `asdf install` in the repo root |
| `asdf: No plugin named python` | `asdf plugin add python https://github.com/asdf-community/asdf-python.git` |
| `uv sync` fails with a TLS / certificate error behind a corporate proxy | `UV_NATIVE_TLS=1 uv sync` (uses the system keychain) |
| uv used the wrong Python | `uv sync --python "$(mise which python)"` (or `asdf where python`) |
| Wrong Python version in a fresh shell | Both managers installed — disable one. For mise: remove `asdf` from the oh-my-zsh `plugins` list; for asdf: drop `eval "$(mise activate zsh)"` |

## Notes

- `.tool-versions` (`python 3.14.0`) and `requires-python` (`>=3.14`) are meant to stay in
  sync — bump both when moving Python.
- `docs/logprobs_report.md` records its results section as run in the original session
  (Python 3.12.10, 66 calls). Findings are version-independent; commands were updated to
  the poetry layout.
