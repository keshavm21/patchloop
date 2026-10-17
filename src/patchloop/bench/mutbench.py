"""MutBench: AST mutations of MBPP+ (evalplus/mbppplus) reference solutions, as repair tasks.

`test_list` gives the visible tests, one per assert. The hidden test is the EvalPlus `test`
script with its extended inputs, run through runpy from a single pytest test; the script is
stored under a name pytest won't collect. Each problem contributes a few mutants (round-robin
across operators, seeded); validation keeps those that fail a hidden test, labels the symptom
from that run, and select() samples about 200, at most 2 per problem, balanced across
operators and symptoms.
"""

import ast
import random
import re
from collections import Counter, defaultdict

from ..models import Status
from .mutate import OPERATORS, all_mutants, normalize
from .spec import TaskSpec

DATASET = "evalplus/mbppplus"
REVISION = "b2d74c91837c3f2a20c1299ae98133cbe7cfa077"
PER_TEST_TIMEOUT_S = 20.0  # the hidden test runs every EvalPlus input in one test
CANDIDATES_PER_PROBLEM = 3
TARGET = 200
MAX_PER_PROBLEM = 2
SEED = 20261017
LABEL_KEYS = ("symptom",)  # set from validation runs, so the manifest records them
INSTRUCTION = (
    "{entry_point} should do the following: {prompt}\n"
    "It has a bug. Fix it so that it does this and passes the tests."
)
SYMPTOMS = {
    Status.TESTS_FAILED: "wrong output",
    Status.RUNTIME_ERROR: "crash",
    Status.TIMEOUT: "hang",
    Status.OOM: "crash",
}
_CALL = re.compile(r"assertion\((\w+)\(\*inp\)")
HIDDEN_RUNNER = """import runpy
from pathlib import Path

import solution

SCRIPT = Path(__file__).with_name("evalplus_check.py")


def test_evalplus():
    exported = {{name: getattr(solution, name) for name in solution.__all__}}
    runpy.run_path(str(SCRIPT), init_globals=exported)
"""


class Unusable(ValueError):
    pass


def load_rows() -> list[dict]:
    from datasets import load_dataset

    return list(load_dataset(DATASET, split="test", revision=REVISION))


def row_slug(row: dict) -> str:
    return f"Mbpp_{row['task_id']}"


def build(row: dict) -> list[TaskSpec]:
    entry = entry_point(row)
    try:
        reference = normalize(row["code"])
    except SyntaxError as e:
        raise Unusable(f"reference doesn't parse: {e.msg}") from None
    visible = _visible_tests(row)
    hidden = HIDDEN_RUNNER.format()
    specs = []
    for operator, site, mutant in candidates(reference, row["task_id"]):
        slug = f"{row_slug(row)}_{operator}_{site}"
        specs.append(
            TaskSpec(
                slug=slug,
                id=f"mutbench/{row['task_id']}/{operator}/{site}",
                instruction=INSTRUCTION.format(entry_point=entry, prompt=row["prompt"].strip()),
                starting_code=mutant,
                reference=reference,
                visible_tests={f"test_{row_slug(row)}.py": visible},
                hidden_tests={f"test_{row_slug(row)}_hidden.py": hidden},
                visible_count=len(row["test_list"]),
                hidden_count=1,
                support={"evalplus_check.py": row["test"]},
                meta={
                    "source": "mutbench",
                    "problem_id": row["task_id"],
                    "entry_point": entry,
                    "operator": operator,
                    "site": site,
                },
            )
        )
    if not specs:
        raise Unusable("no mutation sites")
    return specs


def entry_point(row: dict) -> str:
    match = _CALL.search(row["test"])
    if not match:
        raise Unusable("can't find the function the EvalPlus script calls")
    return match.group(1)


def candidates(reference: str, problem_id) -> list[tuple[str, int, str]]:
    """Up to CANDIDATES_PER_PROBLEM mutants, one operator at a time in a seeded order, so a
    problem's candidates come from different operators where it has the sites."""
    rng = random.Random(f"{SEED}-{problem_id}")
    pools = {}
    for op in OPERATORS:
        found = all_mutants(reference, op)
        rng.shuffle(found)
        if found:
            pools[op.name] = found
    order = list(pools)
    rng.shuffle(order)
    picked, seen = [], set()
    while order and len(picked) < CANDIDATES_PER_PROBLEM:
        for name in list(order):
            if not pools[name]:
                order.remove(name)
                continue
            site, text = pools[name].pop()
            key = ast.dump(ast.parse(text))
            if key in seen:
                continue
            seen.add(key)
            picked.append((name, site, text))
            if len(picked) == CANDIDATES_PER_PROBLEM:
                break
    return picked


def label(spec: TaskSpec, buggy_status: Status) -> None:
    """Record the symptom of the mutant's failing hidden run."""
    spec.meta["symptom"] = SYMPTOMS.get(buggy_status, "crash")


def select(valid: list[TaskSpec]) -> list[TaskSpec]:
    """About TARGET tasks, at most MAX_PER_PROBLEM per problem: round-robin over operators,
    each time taking the candidate whose symptom is rarest so far."""
    rng = random.Random(SEED)
    by_operator = defaultdict(list)
    for spec in sorted(valid, key=lambda s: s.slug):
        by_operator[spec.meta["operator"]].append(spec)
    for specs in by_operator.values():
        rng.shuffle(specs)
    chosen, per_problem, symptoms = [], Counter(), Counter()
    operators = sorted(by_operator)
    while len(chosen) < TARGET and any(by_operator.values()):
        for op in operators:
            pool = [
                s for s in by_operator[op] if per_problem[s.meta["problem_id"]] < MAX_PER_PROBLEM
            ]
            by_operator[op] = pool
            if not pool or len(chosen) >= TARGET:
                continue
            pick = min(pool, key=lambda s: symptoms[s.meta["symptom"]])
            pool.remove(pick)
            chosen.append(pick)
            per_problem[pick.meta["problem_id"]] += 1
            symptoms[pick.meta["symptom"]] += 1
    return chosen


def _visible_tests(row: dict) -> str:
    header = [*row["test_imports"], "from solution import *", ""]
    tests = [
        f"\ndef test_{i:02d}():\n    {line.strip()}\n" for i, line in enumerate(row["test_list"])
    ]
    return "\n".join(header) + "".join(tests)
