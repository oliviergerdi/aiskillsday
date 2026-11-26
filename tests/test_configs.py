import shutil

import pytest
from pydantic import ValidationError

from app.web.configs import RunInput, config_path, list_configs, load_config, save_config


def test_committed_configs_validate():
    names = [c.name for c in list_configs("comparisons")]
    assert {"toy", "petstore"} <= set(names)
    toy = load_config("toy", "comparisons")
    assert (toy.backend, toy.score, toy.before.source) == ("fake", True, "http://localhost:8000/v1")


def test_round_trip_excludes_per_start_fields(tmp_path):
    inp = RunInput(before={"kind": "api", "source": "http://a/v1"}, after={"kind": "api", "source": "http://a/v2"},
                   name="mine", save_config=True, baseline="some-run")
    path = save_config(inp, tmp_path)
    assert "save_config" not in path.read_text() and "baseline" not in path.read_text()
    back = load_config("mine", tmp_path)
    assert back.model_dump(exclude={"save_config", "baseline"}) == inp.model_dump(exclude={"save_config", "baseline"})
    assert (back.save_config, back.baseline) == (False, "auto")


def test_bad_names():
    with pytest.raises(ValueError):
        config_path("../etc", "comparisons")
    with pytest.raises(ValidationError):
        RunInput(before={"kind": "api", "source": "x"}, after={"kind": "api", "source": "x"}, name="a/b")


def test_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config("nope", tmp_path)
    assert list_configs(tmp_path / "none") == []
