"""Benchmark conversion, sampling, splitting and freezing, without Docker or downloads."""

import json
from collections import Counter

import pytest

from patchloop.bench import humanevalfix as hef
from patchloop.bench import mutbench as mb
from patchloop.bench import setup as bench_setup
from patchloop.bench.split import stratified_split
from patchloop.bench.validate import Outcome
from patchloop.models import Status

CHECK = """

def check(candidate):
    assert candidate(1) == 2
    assert True
    assert candidate(2) == 3

check(add_one)
"""
LOOPED = """
def check(candidate):
    import random
    for _ in range(3):
        x = random.randint(0, 9)
        assert candidate(x) == x + 1
"""


def test_check_becomes_one_test_per_assert():
    source, count = hef.check_to_pytest(CHECK, "add_one")
    assert count == 2  # `assert True` is dropped
    assert "from solution import *\ncandidate = add_one" in source
    assert "def test_00():\n    assert candidate(1) == 2" in source
    assert "def test_01():\n    assert candidate(2) == 3" in source
    compile(source, "t.py", "exec")


def test_loops_stay_one_test():
    source, count = hef.check_to_pytest(LOOPED, "add_one")
    assert count == 1
    assert "def test_check():\n    check(add_one)" in source
    compile(source, "t.py", "exec")


def test_indented_sources_are_dedented():
    _, count = hef.check_to_pytest("    def check(f):\n        assert f(1) == 2\n", "f")
    assert count == 1


@pytest.mark.parametrize(
    "src", ["", "def helper():\n    pass\n", "def check(x):\n    assert True\n"]
)
def test_unusable_tests(src):
    with pytest.raises(hef.Unusable):
        hef.check_to_pytest(src, "f")


def test_empty_example_test_borrows_the_first_hidden_assert():
    row = {
        "task_id": "Python/9",
        "entry_point": "add_one",
        "prompt": 'def add_one(x):\n    """Add one."""\n',
        "buggy_solution": "    return x\n",
        "canonical_solution": "    return x + 1\n",
        "test": CHECK,
        "example_test": "",
        "bug_type": "missing logic",
        "failure_symptoms": "incorrect output",
    }
    spec = hef.build(row)
    assert spec.visible_count == 1 and spec.hidden_count == 2
    assert spec.meta["visible_from"] == "first hidden assert"
    assert spec.starting_code.endswith("    return x\n")
    assert spec.reference.endswith("    return x + 1\n")


MBPP_ROW = {
    "task_id": 42,
    "prompt": "Write a function that counts the even numbers in a list.",
    "code": "def count_even(nums):\n    count = 0\n    for n in nums:\n        if n % 2 == 0:\n"
    "            count += 1\n    return count\n",
    "test_imports": [],
    "test_list": ["assert count_even([1, 2, 4]) == 2", "assert count_even([]) == 0"],
    "test": "inputs = [[[1, 2]]]\nresults = [1]\n"
    "for i, (inp, exp) in enumerate(zip(inputs, results)):\n"
    "    assertion(count_even(*inp), exp, 0)\n",
}


def test_mutbench_specs():
    specs = mb.build(MBPP_ROW)
    assert 1 <= len(specs) <= mb.CANDIDATES_PER_PROBLEM
    assert len({s.meta["operator"] for s in specs}) == len(specs)  # spread across operators
    assert len({s.starting_code for s in specs}) == len(specs)
    spec = specs[0]
    assert spec.starting_code != spec.reference
    assert spec.visible_count == 2 and spec.hidden_count == 1
    assert "evalplus_check.py" in spec.support
    assert "count_even should do the following" in spec.instruction
    assert [s.slug for s in mb.build(MBPP_ROW)] == [s.slug for s in specs]  # deterministic


def test_mutbench_hidden_runner_compiles():
    compile(mb.HIDDEN_RUNNER.format(), "test_hidden.py", "exec")


def test_select_caps_per_problem_and_balances():
    specs = []
    for problem in range(150):
        for op in ("flip_comparison", "wrong_variable", "drop_guard"):
            spec = mb.build(MBPP_ROW)[0]
            spec.slug = f"p{problem}_{op}"
            spec.meta = {"problem_id": problem, "operator": op}
            mb.label(spec, Status.TIMEOUT if problem % 10 == 0 else Status.TESTS_FAILED)
            specs.append(spec)
    chosen = mb.select(specs)
    assert len(chosen) == mb.TARGET
    assert max(Counter(s.meta["problem_id"] for s in chosen).values()) <= mb.MAX_PER_PROBLEM
    ops = Counter(s.meta["operator"] for s in chosen)
    assert max(ops.values()) - min(ops.values()) <= 1
    # Hangs are rare (15 problems of 150) but are picked first, up to the cap of 2 per problem.
    assert Counter(s.meta["symptom"] for s in chosen)["hang"] == 15 * mb.MAX_PER_PROBLEM


def test_stratified_split_is_exact_and_deterministic():
    strata = {f"t{i}": ["a", "b", "c"][i % 3] for i in range(162)}
    split = stratified_split(strata)
    assert Counter(split.values()) == {"dev": 41, "test": 121}
    for stratum in "abc":
        dev = sum(split[t] == "dev" for t, s in strata.items() if s == stratum)
        assert 13 <= dev <= 14
    assert stratified_split(strata) == split


def test_freeze_then_verify_catches_a_changed_file(tmp_path, monkeypatch):
    class FakeBench:
        DATASET, REVISION, PER_TEST_TIMEOUT_S = "fake/dataset", "0" * 40, 5.0
        Unusable = hef.Unusable
        load_rows = staticmethod(lambda: [{"task_id": f"Python/{i}"} for i in range(8)])
        row_slug = staticmethod(lambda row: row["task_id"].replace("/", "_"))
        answer = "    return x + 1\n"

        @classmethod
        def build(cls, row):
            spec = hef.build(
                {
                    "task_id": row["task_id"],
                    "entry_point": "add_one",
                    "prompt": "def add_one(x):\n",
                    "buggy_solution": "    return x\n",
                    "canonical_solution": cls.answer,
                    "test": CHECK,
                    "example_test": CHECK,
                    "bug_type": "missing logic",
                    "failure_symptoms": "incorrect output",
                }
            )
            return spec

    monkeypatch.setattr(bench_setup, "BENCHMARKS", tmp_path)
    monkeypatch.setattr(bench_setup, "bench_module", lambda name: FakeBench)
    monkeypatch.setattr(bench_setup, "_image_id", lambda image: "sha256:test")
    monkeypatch.setattr(
        bench_setup,
        "check_all",
        lambda paths, sandbox_for, **kw: {
            p.stem: Outcome(None, Status.TESTS_FAILED) for p in paths
        },
    )
    assert bench_setup.setup("humanevalfix", workers=1, revalidate=False) == 0
    manifest = json.loads((tmp_path / "humanevalfix" / "v1" / "manifest.json").read_text())
    assert len(manifest["tasks"]) == 8 and manifest["split"]["counts"] == {"dev": 2, "test": 6}
    assert manifest["dataset"]["revision"] == "0" * 40

    assert bench_setup.setup("humanevalfix", workers=1, revalidate=False) == 0  # verifies
    FakeBench.answer = "    return 1 + x\n"  # upstream changed
    assert bench_setup.setup("humanevalfix", workers=1, revalidate=False) == 1
