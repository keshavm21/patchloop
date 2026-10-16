from solution import second_largest


def test_basic():
    assert second_largest([1, 3, 2]) == 2


def test_duplicates():
    assert second_largest([4, 4, 3]) == 3


def test_negatives():
    assert second_largest([-1, -5, -3]) == -3


def test_single_element():
    assert second_largest([5]) is None


def test_all_equal():
    assert second_largest([7, 7, 7]) is None


def test_empty():
    assert second_largest([]) is None


def test_two_values():
    assert second_largest([2, 1]) == 1


def test_unsorted():
    assert second_largest([10, 50, 20, 40, 30]) == 40


def test_floats():
    assert second_largest([0.5, 0.25, 0.75]) == 0.5
