import ast

import pytest

from patchloop.bench.mutate import (
    OPERATORS,
    DeleteStatement,
    DropGuard,
    FlipComparison,
    ShiftBound,
    SwapArithmetic,
    SwapBoolean,
    WrongVariable,
    all_mutants,
    normalize,
)

SOURCE = normalize("""
def count_small(nums, limit):
    if not nums:
        return 0
    count = 0
    for i in range(len(nums)):
        if nums[i] < limit and nums[i] != 0:
            count += 1
    return count + 0
""")


def mutants(op):
    return [text for _, text in all_mutants(SOURCE, op)]


def test_flip_comparison():
    got = mutants(FlipComparison)
    assert len(got) == 2
    assert "nums[i] <= limit" in got[0] and "nums[i] == 0" in got[1]


def test_swap_arithmetic():
    got = mutants(SwapArithmetic)
    assert any("count -= 1" in m for m in got) and any("count - 0" in m for m in got)


def test_shift_bound():
    got = mutants(ShiftBound)
    assert any("range(len(nums) - 1)" in m for m in got)
    assert any("nums[i + 1] < limit" in m for m in got)


def test_swap_boolean():
    got = mutants(SwapBoolean)
    assert any("if nums:" in m for m in got)
    assert any(" or nums[i] != 0" in m for m in got)


def test_wrong_variable_uses_another_local():
    got = mutants(WrongVariable)
    assert got and all(m != SOURCE for m in got)
    assert any("range(len(count))" in m for m in got)  # sorted locals wrap: nums -> count


def test_delete_statement_and_drop_guard():
    [deleted] = mutants(DeleteStatement)
    assert "count += 1" not in deleted and "pass" in deleted
    [dropped] = mutants(DropGuard)
    assert "if not nums" not in dropped


@pytest.mark.parametrize("op", OPERATORS, ids=lambda o: o.name)
def test_mutants_parse_differ_and_are_deterministic(op):
    first, second = all_mutants(SOURCE, op), all_mutants(SOURCE, op)
    assert first == second
    original = ast.dump(ast.parse(SOURCE))
    for _, text in first:
        assert ast.dump(ast.parse(text)) != original
