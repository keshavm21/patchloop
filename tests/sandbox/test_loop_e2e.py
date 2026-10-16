"""The whole loop on real Docker with a scripted model: for each example task, a wrong fix
first (its real failures must reach the second prompt), then the reference solution."""

from pathlib import Path

import pytest

from patchloop.agent.loop import solve
from patchloop.config import AgentConfig
from patchloop.llm.fake import FakeLLM
from patchloop.models import Status, StopReason, Task
from patchloop.sandbox.limits import Limits
from patchloop.sandbox.sandbox import DockerSandbox
from patchloop.tracing import Tracer, read_trace

EXAMPLES = Path(__file__).resolve().parents[2] / "benchmarks" / "examples"
WRONG_FIX = "def {name}(*args, **kwargs):\n    return None\n"


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda p: p.stem)
def test_loop_repairs_with_real_feedback(path, run_dir, docker_client):
    task = Task.load(path)
    name = path.stem
    reference = (task.root / task.meta["reference"]).read_text()
    llm = FakeLLM(
        [
            f"```python\n{WRONG_FIX.format(name=name)}```",
            f"## Diagnosis\nThe edge case was wrong.\n\n```python\n{reference}```",
        ]
    )
    sandbox = DockerSandbox(run_dir, Limits(per_test_timeout_s=2), docker_client)
    tracer = Tracer(run_dir / "trace.jsonl", run=f"{task.id}/e2e/r0")
    cfg = AgentConfig(explain_failures=False, reflect=True)

    rec = solve(task, cfg, llm, sandbox, tracer=tracer)

    assert rec.stop_reason is StopReason.SOLVED, rec.attempts[-1].result
    assert rec.solved and rec.final_attempt == 2
    assert rec.hidden_result.executed == task.expected_counts.hidden
    first = rec.attempts[0].result
    assert first.status in (Status.TESTS_FAILED, Status.RUNTIME_ERROR) and first.failures
    second_prompt = llm.calls[1][1]["content"]
    assert f"FAILED {first.failures[0].name.rsplit('::', 1)[-1]}" in second_prompt
    events = [e["event"] for e in read_trace(run_dir / "trace.jsonl")]
    assert events[0] == "start" and events[-2:] == ["hidden_verdict", "stop"]
