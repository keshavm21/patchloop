"""Turn the trusted runner's stdout into an ExecutionResult.

The report and log were produced inside the sandbox, so they are untrusted: the JUnit XML is
parsed with defusedxml, and every string kept from it is length-capped. Anything ambiguous
classifies as something other than PASSED.
"""

import re
from dataclasses import dataclass

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring

from ..models import ExecutionResult, FailedTest, Status

MAX_NAME = 300
MAX_TEXT = 4000  # per failure message or traceback
MAX_LOG = 20000

_EXIT_LINE = re.compile(r"@@PL_EXIT (\d{1,3})")
_EXCEPTION_NAME = re.compile(r"([A-Za-z_][\w.]*)(?::|$)")


@dataclass(frozen=True)
class RunnerOutput:
    exit_code: int
    report: str
    log: str


@dataclass(frozen=True)
class Case:
    name: str
    outcome: str  # "passed", "failed", "error" or "skipped"
    message: str
    detail: str


def parse_runner_output(
    raw: str, *, timed_out: bool, oom: bool, expected: int, duration_s: float
) -> ExecutionResult:
    out = split_sections(raw)
    cases = parse_junit(out.report) if out else None
    found = cases or []
    failures = [_failed_test(c) for c in found if c.outcome in ("failed", "error")]
    status, problems = _classify(
        out, cases, failures, timed_out=timed_out, oom=oom, expected=expected
    )
    return ExecutionResult(
        status=status,
        exit_code=out.exit_code if out else None,
        expected=expected,
        executed=len(found),
        num_passed=_count(found, "passed"),
        num_failed=_count(found, "failed"),
        num_errors=_count(found, "error"),
        num_skipped=_count(found, "skipped"),
        passed_tests=[c.name for c in found if c.outcome == "passed"],
        failures=failures,
        problems=problems,
        log=_tail(out.log if out else raw, MAX_LOG),
        timed_out=timed_out,
        oom=oom,
        duration_s=duration_s,
    )


def split_sections(raw: str) -> RunnerOutput | None:
    """The runner's three sections in order, or None if a sentinel is missing.

    Code under test writes into pytest's log, which the runner prints last, so sentinel-like
    lines it prints can't move the section boundaries.
    """
    lines = [line.rstrip("\r") for line in raw.split("\n")]
    exit_at = exit_code = None
    for i, line in enumerate(lines):
        if m := _EXIT_LINE.fullmatch(line):
            exit_at, exit_code = i, int(m.group(1))
            break
    if exit_at is None or exit_code is None:
        return None
    try:
        report_at = lines.index("@@PL_REPORT", exit_at + 1)
        log_at = lines.index("@@PL_LOG", report_at + 1)
    except ValueError:
        return None
    report = "\n".join(lines[report_at + 1 : log_at]).strip()
    return RunnerOutput(exit_code, report, "\n".join(lines[log_at + 1 :]))


def parse_junit(xml: str) -> list[Case] | None:
    """The testcases in a pytest JUnit report, or None if it is missing or doesn't parse."""
    if not xml:
        return None
    try:
        root = fromstring(xml)
    except (ParseError, DefusedXmlException):
        return None
    if root.tag not in ("testsuites", "testsuite"):
        return None
    cases = []
    for case in root.iter("testcase"):
        name = f"{case.get('classname', '')}::{case.get('name', '')}"
        outcome, node = "passed", None
        for tag, label in (("error", "error"), ("failure", "failed"), ("skipped", "skipped")):
            node = case.find(tag)
            if node is not None:
                outcome = label
                break
        message = node.get("message", "") if node is not None else ""
        detail = (node.text or "") if node is not None else ""
        cases.append(
            Case(_head(name, MAX_NAME), outcome, _head(message, MAX_TEXT), _tail(detail, MAX_TEXT))
        )
    return cases


def _classify(
    out: RunnerOutput | None,
    cases: list[Case] | None,
    failures: list[FailedTest],
    *,
    timed_out: bool,
    oom: bool,
    expected: int,
) -> tuple[Status, list[str]]:
    """The first match wins: host timeout, OOM, per-test timeout, then the exit code."""
    if timed_out:
        return Status.TIMEOUT, ["killed by the host at the wall-clock limit"]
    if oom:
        return Status.OOM, ["killed for exceeding the memory limit"]
    if any(f.kind == "timeout" for f in failures):
        return Status.TIMEOUT, ["a test hit the per-test timeout"]
    if out is None:
        return Status.SANDBOX_ERROR, ["the runner's output sections are missing"]
    code = out.exit_code
    if code == 0:
        problems = _integrity_problems(cases, expected)
        return (Status.INTEGRITY_FAIL, problems) if problems else (Status.PASSED, [])
    if code == 1:
        if cases is None:
            return Status.RUNTIME_ERROR, ["pytest exited 1 without a readable report"]
        if not failures:
            return Status.INTEGRITY_FAIL, ["pytest exited 1 but the report shows no failures"]
        if all(f.kind == "assertion" for f in failures):
            return Status.TESTS_FAILED, []
        return Status.RUNTIME_ERROR, []
    if code in (2, 3):
        return Status.RUNTIME_ERROR, [f"pytest exited {code}: tests could not be imported"]
    if code in (4, 5):
        return Status.SANDBOX_ERROR, [f"pytest exited {code}: usage error or no tests collected"]
    return Status.RUNTIME_ERROR, [f"pytest exited {code}"]


def _integrity_problems(cases: list[Case] | None, expected: int) -> list[str]:
    if cases is None:
        return ["the JUnit report is missing or unreadable"]
    problems = []
    if len(cases) != expected:
        problems.append(f"{len(cases)} tests ran but {expected} were expected")
    for outcome in ("failed", "error", "skipped"):
        if n := _count(cases, outcome):
            problems.append(f"{n} test(s) {outcome} despite exit code 0")
    return problems


def _failed_test(case: Case) -> FailedTest:
    message = case.message
    if case.outcome == "error":
        kind, exception = "error", _exception_name(message) or "Error"
    elif message.startswith("Failed: Timeout"):
        kind, exception = "timeout", "Timeout"
    elif message.startswith(("assert", "AssertionError")):
        kind, exception = "assertion", "AssertionError"
    else:
        kind, exception = "exception", _exception_name(message) or "Exception"
    return FailedTest(
        name=case.name, kind=kind, exception=exception, message=message, traceback=case.detail
    )


def _exception_name(message: str) -> str | None:
    m = _EXCEPTION_NAME.match(message)
    return m.group(1) if m else None


def _count(cases: list[Case], outcome: str) -> int:
    return sum(c.outcome == outcome for c in cases)


def _head(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " ...[truncated]"


def _tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else "[truncated]... " + text[-limit:]
