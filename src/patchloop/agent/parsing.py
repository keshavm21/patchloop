"""Pull the candidate file out of a model reply: exactly one fenced Python block, the whole
replacement file. Zero blocks, or several that disagree, is PARSE_FAILED."""

import ast
import re
from dataclasses import dataclass

# An opening fence, optionally tagged as Python, up to the next closing fence.
_FENCE = re.compile(r"^```[ \t]*([\w+-]*)[ \t]*\n(.*?)^```[ \t]*$", re.DOTALL | re.MULTILINE)
_DIAGNOSIS = re.compile(r"^#+\s*Diagnosis\s*\n(.*?)(?=^```|^#|\Z)", re.DOTALL | re.MULTILINE)
_PYTHON_TAGS = {"python", "py", "python3"}
MAX_DIAGNOSIS = 1000

FORMAT_HELP = (
    "Reply with the complete file in exactly one fenced code block that starts with ```python "
    "and ends with ```."
)


@dataclass(frozen=True)
class Parsed:
    code: str | None
    diagnosis: str | None = None
    error: str | None = None  # why there is no code, phrased as feedback for the model


def parse_reply(text: str) -> Parsed:
    diagnosis = _diagnosis(text)
    blocks = [(tag.lower(), body) for tag, body in _FENCE.findall(text)]
    python = [body for tag, body in blocks if tag in _PYTHON_TAGS]
    candidates = python or [body for tag, body in blocks if not tag]
    if not candidates:
        if blocks:
            problem = "no Python code block"
        else:
            problem = "an unclosed code block" if "```" in text else "no code block"
        return Parsed(None, diagnosis, f"Your reply had {problem}. {FORMAT_HELP}")
    distinct = {body.strip() for body in candidates}
    if len(distinct) > 1:
        error = f"Your reply had {len(candidates)} different code blocks. {FORMAT_HELP}"
        return Parsed(None, diagnosis, error)
    code = candidates[0].strip("\n") + "\n"
    return Parsed(code, diagnosis)


def syntax_error(code: str) -> str | None:
    """A one-line description of the code's syntax error, or None. Parsing never executes."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        return f"line {e.lineno}: {e.msg}"
    return None


def _diagnosis(text: str) -> str | None:
    m = _DIAGNOSIS.search(text)
    if not m or not m.group(1).strip():
        return None
    return m.group(1).strip()[:MAX_DIAGNOSIS]
