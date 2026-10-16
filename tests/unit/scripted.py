"""Scripted results and replies for the agent tests."""

from patchloop.models import ExecutionResult, FailedTest, Status

TESTS = ["test_basic", "test_duplicates", "test_negatives", "test_single_element"]


def reply_with(code: str, before: str = "") -> str:
    return f"{before}```python\n{code}```\n"


def passed(expected: int = 4) -> ExecutionResult:
    names = [f"test_second_largest::{t}" for t in TESTS[:expected]]
    return ExecutionResult(
        status=Status.PASSED,
        exit_code=0,
        expected=expected,
        executed=expected,
        num_passed=expected,
        passed_tests=names,
    )


def failed(*failing: str, exception: str = "AssertionError", expected: int = 4) -> ExecutionResult:
    """A run where the named tests fail with `exception` and the rest of the four pass."""
    status = Status.TESTS_FAILED if exception == "AssertionError" else Status.RUNTIME_ERROR
    kind = "assertion" if exception == "AssertionError" else "exception"
    failures = [
        FailedTest(
            name=f"test_second_largest::{t}",
            kind=kind,
            exception=exception,
            message=f"{exception}: boom in {t}"
            if kind == "exception"
            else "assert 5 is None\n +  where 5 = second_largest([5])",
            traceback=f"def {t}():\n>   assert ...\nE   {exception}\nsolution.py:4: {exception}",
        )
        for t in failing
    ]
    names = [f"test_second_largest::{t}" for t in TESTS if t not in failing]
    return ExecutionResult(
        status=status,
        exit_code=1,
        expected=expected,
        executed=expected,
        num_passed=len(names),
        num_failed=len(failures),
        passed_tests=names,
        failures=failures,
    )
