"""InjectBench tasks are still valid repair tasks (§8.3): planting an instruction must not change
whether the reference passes or the buggy code fails."""

import pytest

from patchloop.bench import injectbench
from patchloop.models import Status, Task


@pytest.fixture(scope="module")
def tasks():
    tasks_dir = injectbench.ROOT / "tasks"
    slugs = injectbench.build_all(tasks_dir)
    return {slug: Task.load(tasks_dir / f"{slug}.json") for slug in slugs}


@pytest.fixture
def run_code(run_sandbox, run_dir):
    def _run(code, tests, expected):
        (run_dir / "solution.py").write_text(code)
        return run_sandbox(run_dir, tests, expected, per_test_timeout_s=2)

    return _run


def slugs():
    return [f"{p.stem}__{c}" for p in injectbench.base_tasks() for c in injectbench.CHANNELS]


@pytest.mark.parametrize("slug", slugs())
def test_reference_passes_both_test_sets(run_code, tasks, slug):
    task = tasks[slug]
    reference = (task.root / task.meta["reference"]).read_text()
    for tests, expected in [
        (task.visible_dir, task.expected_counts.visible),
        (task.hidden_dir, task.expected_counts.hidden),
    ]:
        result = run_code(reference, tests, expected)
        assert result.status is Status.PASSED, (result.problems, result.failures)


@pytest.mark.parametrize("slug", slugs())
def test_planted_buggy_code_still_fails_a_hidden_test(run_code, tasks, slug):
    task = tasks[slug]
    result = run_code(task.starting_code, task.hidden_dir, task.expected_counts.hidden)
    assert result.status is not Status.PASSED
    assert result.executed == task.expected_counts.hidden
