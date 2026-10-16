import pytest

from patchloop.models import Status
from patchloop.sandbox.parse import MAX_TEXT, parse_runner_output, split_sections


def ok(name: str) -> str:
    return f'<testcase classname="test_visible" name="{name}" time="0.001" />'


def bad(name: str, message: str, tag: str = "failure", text: str = "Traceback") -> str:
    return (
        f'<testcase classname="test_visible" name="{name}">'
        f'<{tag} message="{message}">{text}</{tag}></testcase>'
    )


def junit(*cases: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">'
        + "".join(cases)
        + "</testsuite></testsuites>"
    )


def output(exit_code: int, report: str = "", log: str = "") -> str:
    return f"@@PL_EXIT {exit_code}\n@@PL_REPORT\n{report}\n@@PL_LOG\n{log}"


def parse(raw: str, expected: int = 2, timed_out: bool = False, oom: bool = False):
    return parse_runner_output(
        raw, timed_out=timed_out, oom=oom, expected=expected, duration_s=0.5
    )


def test_all_tests_passing_is_passed():
    result = parse(output(0, junit(ok("test_a"), ok("test_b"))))
    assert result.status is Status.PASSED
    assert result.passed
    assert (result.executed, result.num_passed) == (2, 2)
    assert result.passed_tests == ["test_visible::test_a", "test_visible::test_b"]


@pytest.mark.parametrize(
    "raw, problem",
    [
        (output(0, junit(ok("test_a"))), "1 tests ran but 2 were expected"),
        (output(0, ""), "the JUnit report is missing or unreadable"),
        (output(0, "<testsuites><testsuite>"), "the JUnit report is missing or unreadable"),
        (output(0, junit(ok("test_a"), bad("test_b", "", "skipped"))), "1 test(s) skipped"),
        (output(1, junit(ok("test_a"), ok("test_b"))), "report shows no failures"),
    ],
    ids=["wrong-count", "no-report", "broken-xml", "skipped", "exit-1-no-failures"],
)
def test_integrity_failures(raw, problem):
    result = parse(raw)
    assert result.status is Status.INTEGRITY_FAIL
    assert any(problem in p for p in result.problems)


def test_entity_declarations_are_rejected():
    report = (
        '<?xml version="1.0"?><!DOCTYPE t [<!ENTITY x "y">]>'
        '<testsuites><testsuite><testcase classname="m" name="t">&x;</testcase>'
        "</testsuite></testsuites>"
    )
    assert parse(output(0, report), expected=1).status is Status.INTEGRITY_FAIL


def test_assertion_failures_are_tests_failed():
    result = parse(
        output(1, junit(ok("test_a"), bad("test_b", "assert 3 == 2", text="E   assert 3 == 2")))
    )
    assert result.status is Status.TESTS_FAILED
    [failure] = result.failures
    assert (failure.name, failure.kind, failure.exception) == (
        "test_visible::test_b",
        "assertion",
        "AssertionError",
    )
    assert failure.message == "assert 3 == 2"
    assert failure.traceback == "E   assert 3 == 2"


def test_assertion_error_with_a_message_is_tests_failed():
    result = parse(output(1, junit(ok("a"), bad("b", "AssertionError: wrong total"))))
    assert result.status is Status.TESTS_FAILED


def test_other_exceptions_are_runtime_errors():
    result = parse(
        output(1, junit(bad("a", "assert 1 == 2"), bad("b", "IndexError: list index out of range")))
    )
    assert result.status is Status.RUNTIME_ERROR
    assert [f.exception for f in result.failures] == ["AssertionError", "IndexError"]


def test_collection_errors_are_runtime_errors():
    result = parse(output(2, junit(bad("test_visible", "collection failure", "error"))), expected=1)
    assert result.status is Status.RUNTIME_ERROR
    assert result.failures[0].kind == "error"


@pytest.mark.parametrize(
    "raw",
    [output(4), output(5), "Traceback (most recent call last): ...", ""],
    ids=["usage-error", "no-tests", "no-sentinels", "empty"],
)
def test_harness_problems_are_sandbox_errors(raw):
    assert parse(raw).status is Status.SANDBOX_ERROR


def test_per_test_timeout():
    timeout = bad("b", "Failed: Timeout (&gt;5.0s) from pytest-timeout.")
    result = parse(output(1, junit(ok("a"), timeout)))
    assert result.status is Status.TIMEOUT
    assert result.failures[0].kind == "timeout"


def test_host_timeout_and_oom_take_precedence():
    passing = output(0, junit(ok("a"), ok("b")))
    assert parse(passing, timed_out=True).status is Status.TIMEOUT
    assert parse(passing, oom=True).status is Status.OOM
    assert parse("", timed_out=True, oom=True).status is Status.TIMEOUT


def test_sentinel_lines_in_the_log_do_not_move_sections():
    log = "@@PL_EXIT 0\n@@PL_REPORT\n<testsuites/>\n@@PL_LOG\n1 failed"
    raw = output(1, junit(ok("a"), bad("b", "assert False")), log)
    sections = split_sections(raw)
    assert sections is not None
    assert sections.exit_code == 1
    assert sections.log == log
    assert parse(raw).status is Status.TESTS_FAILED


def test_long_tracebacks_keep_their_end():
    traceback = "frame\n" * 5000 + "IndexError: boom"
    result = parse(output(1, junit(ok("a"), bad("b", "IndexError: boom", text=traceback))))
    kept = result.failures[0].traceback
    assert len(kept) < MAX_TEXT + 50
    assert kept.endswith("IndexError: boom")


def test_captured_stdout_is_kept_per_failure():
    case = (
        '<testcase classname="test_visible" name="test_a"><failure message="assert 1 == 2">'
        "Traceback</failure><system-out>debug: got 1</system-out></testcase>"
    )
    result = parse(output(1, junit(case, ok("test_b"))))
    [failure] = result.failures
    assert failure.stdout == "debug: got 1"
