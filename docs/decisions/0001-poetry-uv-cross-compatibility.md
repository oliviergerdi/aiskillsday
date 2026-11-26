# 0001 — Keep pyproject.toml usable by both Poetry and uv

**Date:** 2026-11-26
**Status:** Accepted

## Context

The project is managed with Poetry 2.x (`poetry.lock`, `[tool.poetry] package-mode = false`). We want to move to uv without forcing every contributor and doc to switch on the same day. The project is small (8 direct deps, 38 locked packages) and is not a package: nothing is built or published.

Poetry 2 and uv both read PEP 621 `[project]` and PEP 735 `[dependency-groups]`, which the repo already uses. Four things differ:

1. `requires-python = "^3.14"` is Poetry-only syntax. It is not valid PEP 440 and uv rejects it. `>=3.14` is valid for both.
2. `[build-system]` with `poetry-core` makes uv treat the project as a buildable package. uv would then try to build a package that does not exist.
3. Poetry needs `[tool.poetry] package-mode = false` to skip installing the root project. uv ignores `[tool.poetry]`.
4. Lock files are not interchangeable (`poetry.lock` vs `uv.lock`). Two locks can resolve to different versions.

## Decision

Make `pyproject.toml` the shared source of truth and support both tools during a transition. Use uv as the primary tool and Poetry as a fallback.

- `requires-python = ">=3.14"`.
- Keep dependencies in `[project].dependencies` and `[dependency-groups]` only. Do not add `[tool.poetry.dependencies]`.
- Keep `[tool.poetry] package-mode = false`. Add `[tool.uv] package = false`. Each tool then ignores the other's table.
- Remove `[build-system]`. It is not needed for a non-package project, and it is what makes uv try to build.
- Commit `uv.lock` as the authoritative lock. Keep `poetry.lock` only until the transition ends, then delete it.
- Apply the 7-day dependency cooldown to both tools. The machine-wide `/etc/uv/uv.toml` sets `exclude-newer = "7 days"`, so uv cannot see releases newer than 7 days. Declare the same rule in the repo with `[tool.uv] exclude-newer = "7 days"`. Poetry has no such setting, so `poetry.lock` must be aligned to `uv.lock`: pin the differing packages to the `uv.lock` versions in a temporary `pyproject.toml`, run `poetry lock`, restore `pyproject.toml`, and run `poetry lock` again (it keeps locked versions that still satisfy the ranges). Dependency lower bounds must not require a release newer than the cooldown (`openai==3.55.1`, `pydantic>=2.14.3`, `pyyaml>=6.0.3`).
- `tests/test_project_config.py` fails if `uv.lock` and `poetry.lock` pin different versions or the cooldown is not declared.
- CI runs `uv lock --check` and fails on drift. CI also runs `poetry check --lock` while `poetry.lock` exists. When a dependency changes, update both locks in the same commit.
- README documents `uv sync` / `uv run` first, with Poetry equivalents in one short table.
- Set an end date for Poetry support. After it, delete `poetry.lock` and `[tool.poetry]`, and drop the fallback docs.

## Alternatives considered

- **Hard switch to uv now.** Simplest and no drift risk. Rejected for now only because the team has not agreed to switch. This is the right option if everyone agrees.
- **Stay on Poetry.** No work, but misses uv's speed and its use in the rest of the tooling. Rejected, since uv is already installed.
- **Dual support with no end date.** Drift between the two locks becomes permanent. Rejected. The end date is what keeps dual support cheap.
- **Generate one lock from the other** (for example `uv export` to `requirements.txt`). Loses Poetry's lock semantics and is not a real `poetry.lock`. Rejected.

## Consequences

- Easier: either tool installs from the same `pyproject.toml`. Contributors can move to uv at their own pace.
- Harder: two locks must stay in sync until the transition ends. Resolvers can pick different versions, so "works on my machine" differences are possible. The CI checks above are required, not optional.
- uv creates `.venv/` in the project by default, while Poetry keeps its venv in a cache. The README line "No `.venv/` in the project" must change. `.venv/` is already in `.gitignore`.
- `poetry.toml` stays in `.gitignore` until Poetry is dropped.
- A dependency released in the last 7 days cannot be locked. A new bound or pin must wait until the release is 7 days old. Bounds in this change were lowered for this reason.
- Aligning `poetry.lock` takes the extra steps above. Dropping Poetry removes them.

## Verification status

Verified on 2026-11-26 in the UV-1 worktree, with `UV_NATIVE_TLS=1` for uv and a CA bundle plus a small `sitecustomize` shim that turns off Python's strict X.509 check for the Zscaler root CA for Poetry:

- uv: `uv lock --check`, `uv sync` and `uv run pytest -q` pass.
- Poetry 2.5.1: `poetry check --lock`, `poetry install --no-interaction` and `poetry run pytest -q` pass.
- `uv.lock` and `poetry.lock` pin identical versions.

The CA bundle and the `sitecustomize` shim are local workarounds for the Zscaler proxy, not repo requirements. The repo has no CI yet, so the CI checks in the Decision section (`uv lock --check`, `poetry check --lock`) are a follow-up. The Poetry end date is also still to be set.
