"""The example tasks in benchmarks/examples/ are valid (§8.3): the reference solution passes the
visible and hidden tests, the buggy starting code fails at least one hidden test, and the
recorded test counts are the ones that run."""

from pathlib import Path

import pytest

from patchloop.models import Status, Task

EXAMPLES = Path(__file__).resolve().parents[2] / "benchmarks" / "examples"
TASKS = sorted(EXAMPLES.glob("*.json"))


@pytest.fixture
def run_code(run_sandbox, run_dir):
    def _run(code: str, tests: Path, expected: int):
        (run_dir / "solution.py").write_text(code)
        return run_sandbox(run_dir, tests, expected, per_test_timeout_s=2)

    return _run


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.stem)
def test_reference_passes_everything(run_code, path):
    task = Task.load(path)
    reference = (task.root / task.meta["reference"]).read_text()
    for tests, expected in [
        (task.visible_dir, task.expected_counts.visible),
        (task.hidden_dir, task.expected_counts.hidden),
    ]:
        result = run_code(reference, tests, expected)
        assert result.status is Status.PASSED, (result.problems, result.failures)


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.stem)
def test_buggy_code_fails_a_hidden_test(run_code, path):
    task = Task.load(path)
    result = run_code(task.starting_code, task.hidden_dir, task.expected_counts.hidden)
    assert result.status is not Status.PASSED
    assert result.executed == task.expected_counts.hidden


def test_there_are_five_examples():
    assert len(TASKS) == 5
