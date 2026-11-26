"""Guards for UV-1: pyproject.toml works with both Poetry and uv."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def _dep_names(deps: list[str]) -> set[str]:
    return {re.split(r"[\s(<>=!~;\[]", d.strip(), maxsplit=1)[0].lower().replace("_", "-") for d in deps}


def test_pyproject_uv_and_poetry_settings():
    doc = _pyproject()
    assert doc["project"]["requires-python"] == ">=3.14"
    assert doc["tool"]["uv"]["package"] is False
    assert doc["tool"]["poetry"]["package-mode"] is False
    assert "build-system" not in doc


def test_dependencies_not_lost():
    doc = _pyproject()
    names = _dep_names(doc["project"]["dependencies"])
    expected = {"openai", "fastapi", "uvicorn", "typer", "httpx", "pydantic", "jinja2", "pyyaml"}
    assert expected <= names
    assert "pytest" in _dep_names(doc["dependency-groups"]["dev"])


def test_openai_pinned_to_3_55_1():
    deps = _pyproject()["project"]["dependencies"]
    specs = [d.replace(" ", "").replace("(", "").replace(")", "") for d in deps]
    assert "openai==3.55.1" in specs


def test_readme_documents_uv_and_poetry():
    text = (ROOT / "README.md").read_text()
    assert "uv sync" in text
    assert "uv run" in text
    assert "poetry install" in text
    assert text.index("uv sync") < text.index("poetry install")
    assert "No `.venv/` in the project" not in text


def test_design_doc_uses_uv_run_pytest():
    text = (ROOT / "docs" / "nparity-design.md").read_text()
    assert "uv run pytest" in text
    assert "poetry run pytest" not in text
