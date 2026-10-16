"""Shared types. The sandbox produces an ExecutionResult; the loop and the eval code consume it."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class Status(StrEnum):
    """Outcome of running one candidate. The first seven come from a sandbox run; the last
    three are decided on the host before any container starts."""

    PASSED = "PASSED"
    TESTS_FAILED = "TESTS_FAILED"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    TIMEOUT = "TIMEOUT"
    OOM = "OOM"
    INTEGRITY_FAIL = "INTEGRITY_FAIL"
    SANDBOX_ERROR = "SANDBOX_ERROR"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    PARSE_FAILED = "PARSE_FAILED"


class FailedTest(BaseModel):
    """One failing test from the JUnit report. Untrusted sandbox output, length-capped."""

    name: str  # "<module>::<test>"
    kind: Literal["assertion", "exception", "timeout", "error"]
    exception: str  # e.g. "AssertionError", "IndexError"
    message: str
    traceback: str


class ExecutionResult(BaseModel):
    status: Status
    exit_code: int | None = None  # pytest's exit code, when the runner reported one
    expected: int | None = None  # how many tests the task says should run
    executed: int = 0
    num_passed: int = 0
    num_failed: int = 0
    num_errors: int = 0
    num_skipped: int = 0
    passed_tests: list[str] = []
    failures: list[FailedTest] = []
    problems: list[str] = []  # why a run that isn't a plain test failure didn't pass
    log: str = ""
    timed_out: bool = False  # killed by the host at the wall-clock limit
    oom: bool = False
    duration_s: float = 0.0

    @property
    def passed(self) -> bool:
        return self.status is Status.PASSED
