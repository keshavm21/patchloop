"""HumanEvalFix: the Python subset of bigcode/humanevalpack, as repair tasks.

The starting file is `prompt + buggy_solution`, the reference is `prompt + canonical_solution`,
`example_test` becomes the visible tests and `test` the hidden ones. HumanEvalPack writes its
tests as `def check(fn): assert ...`; each assert becomes its own pytest test where possible.
"""

import ast
import textwrap

from .spec import TaskSpec

DATASET = "bigcode/humanevalpack"
REVISION = "9a41762f73a8cb23bb5811b73d5aab164efcf378"  # pinned: re-running setup is reproducible
PER_TEST_TIMEOUT_S = 5.0
INSTRUCTION = "Fix the bugs in {entry_point} so that it matches its docstring and passes the tests."


class Unusable(ValueError):
    """A dataset row that can't become a task; the message says why, for the drop log."""


def load_rows() -> list[dict]:
    from datasets import load_dataset

    return list(load_dataset(DATASET, "python", split="test", revision=REVISION))


def row_slug(row: dict) -> str:
    return row["task_id"].replace("/", "_")


def build(row: dict) -> TaskSpec:
    entry = row["entry_point"]
    hidden, hidden_count = check_to_pytest(row["test"], entry)
    visible_from = "example_test"
    try:
        visible, visible_count = check_to_pytest(row["example_test"], entry)
    except Unusable:
        # A few rows have no usable example_test: borrow the first hidden assert.
        visible, visible_count = first_assert_test(row["test"], entry), 1
        visible_from = "first hidden assert"
    slug = row_slug(row)
    return TaskSpec(
        slug=slug,
        id=f"humanevalfix/{row['task_id']}",
        instruction=INSTRUCTION.format(entry_point=entry),
        starting_code=_file(row["prompt"], row["buggy_solution"]),
        reference=_file(row["prompt"], row["canonical_solution"]),
        visible_tests={f"test_{slug}.py": visible},
        hidden_tests={f"test_{slug}_hidden.py": hidden},
        visible_count=visible_count,
        hidden_count=hidden_count,
        meta={
            "source": "humanevalfix",
            "task_id": row["task_id"],
            "entry_point": entry,
            "bug_type": row["bug_type"],
            "failure_symptoms": row["failure_symptoms"],
            "visible_from": visible_from,
        },
    )


def check_to_pytest(check_src: str, entry_point: str) -> tuple[str, int]:
    """Turn `def check(fn): assert ...` source into a pytest file: (source, number of tests).

    One test per assert when check() is nothing but asserts; otherwise (loops, helpers,
    randomness) check() is kept whole as a single test.
    """
    check_fn, imports = _parse_check(check_src)
    param = check_fn.args.args[0].arg if check_fn.args.args else entry_point
    header = _header(imports, param, entry_point)
    body = [s for s in check_fn.body if not _is_constant_assert(s)]
    if not body:
        raise Unusable("check() has no assertions")
    if all(isinstance(s, ast.Assert) for s in body):
        tests = [f"\ndef test_{i:02d}():\n    {ast.unparse(s)}\n" for i, s in enumerate(body)]
        return "\n".join(header) + "".join(tests), len(body)
    check_fn.body = body
    single = f"\n{ast.unparse(check_fn)}\n\n\ndef test_check():\n    check({entry_point})\n"
    return "\n".join(header) + single, 1


def first_assert_test(check_src: str, entry_point: str) -> str:
    check_fn, imports = _parse_check(check_src)
    param = check_fn.args.args[0].arg if check_fn.args.args else entry_point
    asserts = [s for s in check_fn.body if isinstance(s, ast.Assert) and not _is_constant_assert(s)]
    if not asserts:
        raise Unusable("no usable example_test, and no plain assert in test to borrow")
    header = _header(imports, param, entry_point)
    return "\n".join(header) + f"\ndef test_00():\n    {ast.unparse(asserts[0])}\n"


def _header(imports: list[str], param: str, entry_point: str) -> list[str]:
    alias = [f"{param} = {entry_point}"] if param != entry_point else []
    return [*imports, "from solution import *", *alias, ""]


def _parse_check(src: str) -> tuple[ast.FunctionDef, list[str]]:
    if not src.strip():
        raise Unusable("empty test source")
    try:
        tree = ast.parse(textwrap.dedent(src))
    except SyntaxError as e:
        raise Unusable(f"test source doesn't parse: {e.msg}") from None
    checks = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "check"]
    if len(checks) != 1:
        raise Unusable("test source has no single check() function")
    imports = [ast.unparse(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    return checks[0], imports


def _is_constant_assert(stmt: ast.stmt) -> bool:
    """`assert True` and the like, which HumanEvalPack uses as placeholders."""
    return isinstance(stmt, ast.Assert) and isinstance(stmt.test, ast.Constant)


def _file(prompt: str, body: str) -> str:
    return (prompt + body).rstrip() + "\n"
