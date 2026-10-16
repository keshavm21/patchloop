from scripted import failed, passed, reply_with
from typer.testing import CliRunner

from patchloop import __version__
from patchloop.agent.loop import solve
from patchloop.cli import app
from patchloop.config import AgentConfig
from patchloop.llm.fake import FakeLLM
from patchloop.sandbox.fake import FakeSandbox
from patchloop.tracing import Tracer


def test_version_flag_prints_version():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout == f"patchloop {__version__}\n"


def test_solve_needs_a_model(task):
    result = CliRunner().invoke(app, ["solve", str(task.root / "second_largest.json")])
    assert result.exit_code == 2
    assert "no model set" in result.output


def test_solve_needs_a_key_for_hosted_models(task, monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    path = str(task.root / "second_largest.json")
    result = CliRunner().invoke(app, ["solve", path, "--model", "some-model"])
    assert result.exit_code == 2
    assert "LLM_API_KEY is not set" in result.output


def test_replay_renders_a_trace(task, tmp_path):
    fixed = "def second_largest(nums):\n    return 2\n"

    def results(code, tests_dir):
        if tests_dir == task.hidden_dir:
            return passed(9)
        return passed() if code == fixed else failed("test_single_element")

    llm = FakeLLM([reply_with("def second_largest(nums):\n    return 1\n"), reply_with(fixed)])
    tracer = Tracer(tmp_path / "trace.jsonl", run="r")
    solve(task, AgentConfig(explain_failures=False), llm, FakeSandbox(results), tracer=tracer)

    result = CliRunner().invoke(app, ["replay", str(tmp_path)])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "attempt 1  run → 3/4 passed" in out
    assert "+    return 2" in out
    assert "hidden     run → 9/9 passed" in out
    assert "SOLVED" in out
