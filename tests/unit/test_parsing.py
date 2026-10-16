import pytest

from patchloop.agent.parsing import parse_reply, syntax_error

CODE = "def f():\n    return 1\n"


@pytest.mark.parametrize("tag", ["python", "py", "Python3", ""])
def test_one_block_is_the_file(tag):
    parsed = parse_reply(f"Here you go:\n```{tag}\n{CODE}```\nDone.")
    assert parsed.code == CODE
    assert parsed.error is None


def test_python_block_wins_over_other_blocks():
    reply = f"```bash\npytest -q\n```\n```python\n{CODE}```\n"
    assert parse_reply(reply).code == CODE


def test_identical_duplicate_blocks_are_fine():
    assert parse_reply(f"```python\n{CODE}```\nagain:\n```python\n{CODE}```").code == CODE


def test_conflicting_blocks_fail():
    parsed = parse_reply(f"```python\n{CODE}```\n```python\ndef g():\n    pass\n```")
    assert parsed.code is None
    assert "2 different code blocks" in parsed.error


@pytest.mark.parametrize(
    ("reply", "problem"),
    [
        ("just prose", "no code block"),
        ("```python\ndef f():\n    return 1\n", "an unclosed code block"),
        ("```bash\nls\n```", "no Python code block"),
    ],
)
def test_no_usable_block(reply, problem):
    parsed = parse_reply(reply)
    assert parsed.code is None
    assert problem in parsed.error and "```python" in parsed.error


def test_diagnosis_is_extracted():
    reply = f"## Diagnosis\nThe loop never advances.\nIt hangs.\n\n```python\n{CODE}```"
    parsed = parse_reply(reply)
    assert parsed.diagnosis == "The loop never advances.\nIt hangs."
    assert parsed.code == CODE


def test_syntax_error_is_one_line():
    assert syntax_error("def f(:\n    pass\n").startswith("line 1:")
    assert syntax_error(CODE) is None
