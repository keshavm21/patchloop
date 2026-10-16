"""What the model sees about an attempt, at the configured granularity:

- L0: nothing
- L1: the status and how many tests passed
- L2: L1 plus each failing test's name, exception and message
- L3: L2 plus a truncated traceback (with pytest's expected-vs-actual), captured stdout and
  a note on tests that passed before and fail now

Everything here is deterministic, so prompts (and the replay fixtures keyed on them) are too.
"""

import re

from ..models import Attempt, ExecutionResult, Status

MAX_FAILURES = 3
TRACEBACK_LINES = 15
MAX_STDOUT = 1000
MAX_FEEDBACK = 8000  # characters, about 2k tokens
_HOST_STATUSES = {Status.PARSE_FAILED, Status.SYNTAX_ERROR, Status.POLICY_BLOCKED}
_DATA_TAGS = ("task", "code", "tests", "execution_output")
_CAPTURE_BANNER = re.compile(r"^-+ Captured \w+(?: \w+)? -+$", re.MULTILINE)
_SANDBOX_PATHS = re.compile(r"/work/(?:solution|tests)/")
_CLOSING_TAG = re.compile(r"</(\s*(?:" + "|".join(_DATA_TAGS) + r")\b)", re.IGNORECASE)


def escape_data(text: str) -> str:
    """Neutralize closing data tags in untrusted text, so it can't end its own tag early."""
    return _CLOSING_TAG.sub(r"<\\/\1", text)


def render(attempt: Attempt, level: str) -> str | None:
    """The <execution_output> block for an attempt, or None at L0."""
    if level == "L0":
        return None
    result = attempt.result
    lines = [_status_line(result)]
    if result.status in _HOST_STATUSES:  # the reason is the whole message, at every level
        lines += result.problems
    elif level in ("L2", "L3"):
        lines += _failure_lines(result, full=level == "L3")
        if not result.failures:
            lines += result.problems
        if level == "L3" and attempt.regressions:
            lines.append(
                "Regression: these tests passed on an earlier attempt and fail now: "
                + ", ".join(_short(name) for name in attempt.regressions)
            )
    body = _SANDBOX_PATHS.sub("", "\n".join(lines))
    if len(body) > MAX_FEEDBACK:
        body = body[:MAX_FEEDBACK] + "\n[... feedback truncated]"
    return f'<execution_output attempt="{attempt.n}">\n{escape_data(body)}\n</execution_output>'


def summarize(attempt: Attempt, level: str) -> str | None:
    """The one-line history entry for an earlier attempt, or None at L0."""
    if level == "L0":
        return None
    result = attempt.result
    text = f"attempt {attempt.n}: {_status_line(result).removeprefix('status: ')}"
    if level != "L1" and result.failures:
        first = result.failures[0]
        more = f" (+{len(result.failures) - 1} more)" if len(result.failures) > 1 else ""
        text += f"; {first.exception} in {_short(first.name)}{more}"
    return text


def regressions(earlier: list[Attempt], result: ExecutionResult) -> list[str]:
    """Tests that passed on some earlier attempt that ran, and failed on this one."""
    if not result.failures:
        return []
    passed_before = {name for a in earlier if a.ran for name in a.result.passed_tests}
    return sorted(passed_before & {f.name for f in result.failures})


def error_signature(result: ExecutionResult) -> tuple:
    """What "the same error again" means for the no-progress check."""
    failures = tuple(sorted((f.name, f.exception) for f in result.failures))
    return (result.status, failures, () if failures else tuple(result.problems))


def _status_line(result: ExecutionResult) -> str:
    if result.status in _HOST_STATUSES:
        return f"status: {result.status} (the code did not run)"
    total = result.expected or result.executed
    return f"status: {result.status} ({result.num_passed} of {total} tests passed)"


def _failure_lines(result: ExecutionResult, *, full: bool) -> list[str]:
    lines = []
    for f in result.failures[:MAX_FAILURES]:
        # The first line only: the rest (pytest's expected-vs-actual, or the candidate's
        # traceback) is in the traceback that L3 shows next.
        message = f.message.split("\n", 1)[0]
        lines.append(f"FAILED {_short(f.name)}: {_label(f.exception, message)}")
        if full:
            if f.traceback:
                lines += ["  " + line for line in _tail_lines(f.traceback)]
            if out := _CAPTURE_BANNER.sub("", f.stdout).strip():
                lines += ["  stdout:", *("    " + line for line in out[:MAX_STDOUT].splitlines())]
    if len(result.failures) > MAX_FAILURES:
        lines.append(f"... and {len(result.failures) - MAX_FAILURES} more failing tests")
    return lines


def _label(exception: str, message: str) -> str:
    message = message.strip()
    if not message or message.startswith(exception):
        return message or exception
    return message if exception == "AssertionError" else f"{exception}: {message}"


def _tail_lines(traceback: str) -> list[str]:
    """The last TRACEBACK_LINES lines, with runs of identical lines collapsed."""
    collapsed: list[str] = []
    repeats = 0
    for line in traceback.rstrip().splitlines():
        if collapsed and line == collapsed[-1]:
            repeats += 1
            continue
        if repeats:
            collapsed.append(f"[previous line repeated {repeats} more times]")
            repeats = 0
        collapsed.append(line)
    if repeats:
        collapsed.append(f"[previous line repeated {repeats} more times]")
    return collapsed[-TRACEBACK_LINES:]


def _short(name: str) -> str:
    """test_visible::test_single_element -> test_single_element"""
    return name.rsplit("::", 1)[-1]
