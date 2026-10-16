from solution import second_largest


def test_basic():
    assert second_largest([1, 3, 2]) == 2


def test_duplicates():
    assert second_largest([4, 4, 3]) == 3


def test_negatives():
    assert second_largest([-1, -5, -3]) == -3


def test_single_element():
    assert second_largest([5]) is None
