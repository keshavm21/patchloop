"""Status classification against real Docker, using benign variants of one small task."""

from pathlib import Path

import pytest

from patchloop.models import ExecutionResult, Status

CASE = Path(__file__).parent / "cases" / "second_largest"
GRACE_S = 5.0


@pytest.fixture
def run(run_sandbox):
    def _run(
        solution: str, expected: int = 4, tests: Path = CASE / "tests", **limits
    ) -> ExecutionResult:
        return run_sandbox(CASE / solution, tests, expected, **limits)

    return _run


def test_correct_solution_passes(run):
    result = run("correct")
    assert result.status is Status.PASSED, result.problems
    assert (result.exit_code, result.executed, result.num_passed) == (0, 4, 4)


def test_wrong_output_is_tests_failed(run):
    result = run("wrong_value")
    assert result.status is Status.TESTS_FAILED
    assert result.num_failed == 3
    assert {f.kind for f in result.failures} == {"assertion"}
    assert result.passed_tests == ["test_second_largest::test_single_element"]


def test_exception_is_runtime_error(run):
    result = run("index_error")
    assert result.status is Status.RUNTIME_ERROR
    [failure] = result.failures
    assert failure.name == "test_second_largest::test_single_element"
    assert failure.exception == "IndexError"
    assert "uniq[-2]" in failure.traceback


def test_import_failure_is_runtime_error(run):
    result = run("import_error")
    assert result.status is Status.RUNTIME_ERROR
    assert result.exit_code == 2
    assert "ValueError" in result.log


def test_wrong_test_count_is_integrity_fail(run):
    result = run("correct", expected=5)
    assert result.status is Status.INTEGRITY_FAIL
    assert result.problems == ["4 tests ran but 5 were expected"]


def test_no_tests_collected_is_retried_then_integrity_fail(run, run_dir):
    (run_dir / "notes.txt").write_text("no tests here\n")
    result = run("correct", expected=1, tests=run_dir)
    assert result.status is Status.INTEGRITY_FAIL
    assert result.exit_code == 5


def test_per_test_timeout(run):
    result = run("slow", per_test_timeout_s=1)
    assert result.status is Status.TIMEOUT
    assert not result.timed_out
    assert {f.kind for f in result.failures} == {"timeout"}


def test_host_kills_at_the_wall_limit(run):
    result = run("slow", per_test_timeout_s=60, wall_timeout_s=2)
    assert result.status is Status.TIMEOUT
    assert result.timed_out
    assert result.duration_s < 2 + GRACE_S
