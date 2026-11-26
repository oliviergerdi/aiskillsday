---
id: UV-1
type: Task
title: Make pyproject.toml work with both Poetry and uv
---

## Description

Implement ADR 0001 (`docs/decisions/0001-poetry-uv-cross-compatibility.md`). `pyproject.toml` must install with both Poetry 2.x and uv. uv is the primary tool and Poetry is a fallback until an agreed end date.

Changes:
- `requires-python = ">=3.14"` (the caret form is Poetry-only and uv rejects it).
- Keep `[tool.poetry] package-mode = false` and add `[tool.uv] package = false`.
- Remove `[build-system]`.
- Commit `uv.lock`. Keep `poetry.lock` during the transition.
- Update README and `docs/nparity-design.md` to put `uv sync` / `uv run` first, with Poetry equivalents.
- Remove the "no `.venv/` in the project" guidance from the README.

## Acceptance Criteria

- `pyproject.toml` has `requires-python = ">=3.14"`, `[tool.uv] package = false` and `[tool.poetry] package-mode = false`, and has no `[build-system]` table.
- `uv lock --check` passes and `uv.lock` is committed.
- `uv sync && uv run pytest -q` passes.
- `poetry check --lock` and `poetry install --no-interaction` pass, and `poetry run pytest -q` passes.
- README documents `uv sync` and `uv run` first, with a short Poetry equivalents table, and no longer says there is no `.venv/` in the project.
- `docs/nparity-design.md` references to `poetry run pytest` are updated to `uv run pytest`.
- ADR 0001 status is changed to Accepted after both tools are verified.
