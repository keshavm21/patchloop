"""Shared types. The sandbox produces an ExecutionResult; the loop and the eval code consume it."""

import json
from enum import StrEnum
from pathlib import Path
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
    stdout: str = ""  # what the test printed, including the candidate's output


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


def host_result(status: Status, problem: str) -> ExecutionResult:
    """A result decided on the host before any container starts (parse, syntax, policy)."""
    return ExecutionResult(status=status, problems=[problem])


class StopReason(StrEnum):
    SOLVED = "SOLVED"
    MAX_ATTEMPTS = "MAX_ATTEMPTS"
    NO_PROGRESS = "NO_PROGRESS"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    INFRA_ERROR = "INFRA_ERROR"  # model API or Docker failed; excluded from agent metrics


class ExpectedCounts(BaseModel):
    visible: int
    hidden: int


class Task(BaseModel):
    """One repair task: a JSON file whose test folders are relative to the file's folder."""

    id: str
    mode: Literal["repair"] = "repair"
    instruction: str
    entrypoint: Literal["solution.py"] = "solution.py"  # the tests import `solution`
    files: dict[str, str]
    visible_tests: str
    hidden_tests: str
    expected_counts: ExpectedCounts
    meta: dict = {}
    root: Path = Path(".")  # set by load(); not part of the file

    @classmethod
    def load(cls, path: Path) -> "Task":
        path = Path(path)
        return cls.model_validate({**json.loads(path.read_text()), "root": path.parent})

    @property
    def starting_code(self) -> str:
        return self.files[self.entrypoint]

    @property
    def visible_dir(self) -> Path:
        return self.root / self.visible_tests

    @property
    def hidden_dir(self) -> Path:
        return self.root / self.hidden_tests


class Usage(BaseModel):
    """Model usage for one call or a sum of calls."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None  # None when the model has no price in the config
    latency_s: float = 0.0  # of the successful tries only
    calls: int = 0
    cached_calls: int = 0
    retries: int = 0
    retry_wait_s: float = 0.0  # failed tries plus backoff: the provider's time, not the agent's

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "Usage") -> "Usage":
        cost = None
        if self.cost_usd is not None or other.cost_usd is not None:
            cost = (self.cost_usd or 0.0) + (other.cost_usd or 0.0)
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=cost,
            latency_s=self.latency_s + other.latency_s,
            calls=self.calls + other.calls,
            cached_calls=self.cached_calls + other.cached_calls,
            retries=self.retries + other.retries,
            retry_wait_s=self.retry_wait_s + other.retry_wait_s,
        )


class Attempt(BaseModel):
    n: int
    reply: str
    diagnosis: str | None = None  # reflect mode only
    code: str | None = None  # None when the reply had no usable code block
    code_hash: str | None = None
    result: ExecutionResult
    ran: bool = False  # whether the code reached the sandbox
    regressions: list[str] = []  # tests that passed on an earlier attempt and fail now
    summary: str  # the one-line history entry later prompts show
    usage: Usage = Usage()
    finish_reason: str | None = None  # "length": the reply was cut off at max_output_tokens


class RunRecord(BaseModel):
    """Everything about one run of the loop on one task; one line of records.jsonl."""

    task_id: str
    config: str
    repeat: int = 0
    model: str
    prompt_version: str
    attempts: list[Attempt] = []
    stop_reason: StopReason | None = None
    final_attempt: int | None = None  # whose code the hidden tests judged; None: starting code
    hidden_result: ExecutionResult | None = None
    failure_explanation: str | None = None
    infra_error: str | None = None
    usage: Usage = Usage()  # the repair attempts only
    explanation_usage: Usage = Usage()
    duration_s: float = 0.0

    @property
    def solved(self) -> bool:
        return self.hidden_result is not None and self.hidden_result.passed
