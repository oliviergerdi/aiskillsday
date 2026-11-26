# aiskillsday

Probing `logprobs` behaviour of DeepSeek Flash on Fireworks AI (OpenAI-compatible API,
custom `base_url`). Results feed the nParity evaluator specs in `docs/`.

## Layout

```
.
├── .tool-versions          python 3.14.0 — read by mise AND asdf
├── pyproject.toml          deps + requires-python ^3.14 (poetry, package-mode = false)
├── poetry.lock             locked dependency set — commit this
├── proto/
│   ├── logprobs_test.py    the one script: 16 experiments (E0–E15)
│   ├── raw/                57 raw API responses, one file per recorded call
│   └── results.json        machine-readable summary of every experiment
└── docs/                   specs + writeup (build, evaluator, llm layer, results report)
```

**`pyproject.toml` + `poetry.lock` are the source of truth** for dependencies.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | **3.14.x** | pinned in `.tool-versions`; install via **mise or asdf** (either works) |
| Poetry | **2.x** (tested on 2.5.1) | manages the virtualenv + dependencies |
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

### 2. Dependencies via poetry

```bash
poetry install
```

That's it. Poetry resolves Python from `PATH` (so it picks up the mise/asdf 3.14), creates
a virtualenv **outside the repo** by default
(`~/Library/Caches/pypoetry/virtualenvs/aiskillsday-*-py3.14` on macOS) and installs
`openai` from the lock file. No `.venv/` in the project — keep it that way.

Prefer a local `.venv/` anyway? Then opt in per-checkout (creates `poetry.toml`):

```bash
poetry config virtualenvs.in-project true --local
rm -rf "$(poetry env info --path)" && poetry install
```

`package-mode = false` in `pyproject.toml` is deliberate: there is no importable
`aiskillsday` package, so poetry must not try to build/install the project itself.

### 3. API key

```bash
export FIREWORKS_API_KEY=...        # never commit, never hardcode
```

Shell-profile export or a secret manager both fine — the script only reads the env var.

## Running

```bash
poetry run python proto/logprobs_test.py                      # all 16 experiments, ~30 s, ~$0.005
poetry run python proto/logprobs_test.py --exp E4 E7          # subset
poetry run python proto/logprobs_test.py --model <fireworks-model-id>
```

Writes to its own directory: `proto/raw/<EXP>_<n>.json` and `proto/results.json`
(both regenerated per run — `raw/` keeps one file per recorded call).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `mise ERROR No version is set for python` | You're outside the repo (no `.tool-versions` applies). `cd` in, or set a default: `mise use -g python@3.14.0` |
| `asdf: No preset version installed for command python` | `asdf install` in the repo root |
| `asdf: No plugin named python` | `asdf plugin add python https://github.com/asdf-community/asdf-python.git` |
| Poetry used the wrong Python | `poetry env use "$(mise which python)"` (or `asdf where python`), then `poetry install` |
| `The current project could not be installed: No file/folder found for package aiskillsday` | Ensure `[tool.poetry] package-mode = false` is in `pyproject.toml` |
| `poetry install` warns about a foreign virtualenv | A hand-made `.venv/` shadows poetry's. Delete it and re-run `poetry install` |
| Wrong Python version in a fresh shell | Both managers installed — disable one. For mise: remove `asdf` from the oh-my-zsh `plugins` list; for asdf: drop `eval "$(mise activate zsh)"` |

## Notes

- `.tool-versions` (`python 3.14.0`) and `requires-python` (`^3.14`) are meant to stay in
  sync — bump both when moving Python.
- `docs/logprobs_report.md` records its results section as run in the original session
  (Python 3.12.10, 66 calls). Findings are version-independent; commands were updated to
  the poetry layout.
