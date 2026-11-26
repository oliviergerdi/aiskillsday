from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app.main import app
from nparity import pipeline, store
from nparity.cli import app as cli
from nparity.retry import RetryPolicy


def test_show_and_runs(tmp_path):
    r = pipeline.run(pipeline.RunConfig(old="http://testserver/v1", new="http://testserver/v2", workers=1,
                                        retry=RetryPolicy(base=0.0)), TestClient(app))
    store.save(r, tmp_path)
    runner = CliRunner()
    out = runner.invoke(cli, ["show", r.id, "--runs-dir", str(tmp_path)])
    assert out.exit_code == 0, out.output
    assert "Regressions: 3" in out.output
    assert "Answer key: 10/10 correct" in out.output
    listed = runner.invoke(cli, ["runs", "--runs-dir", str(tmp_path)])
    assert r.id in listed.output


def test_freeze(tmp_path):
    r = pipeline.run(pipeline.RunConfig(old="http://testserver/v1", new="http://testserver/v2", workers=1,
                                        retry=RetryPolicy(base=0.0)), TestClient(app))
    store.save(r, tmp_path)
    out = CliRunner().invoke(cli, ["freeze", r.id, "--runs-dir", str(tmp_path)])
    assert out.exit_code == 0, out.output
    demo = store.load("demo", tmp_path)
    assert demo.id == "demo" and demo.score.correct == 10
