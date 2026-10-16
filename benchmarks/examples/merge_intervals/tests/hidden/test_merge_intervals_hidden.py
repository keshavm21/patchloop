from solution import merge_intervals


def test_overlapping():
    assert merge_intervals([[1, 3], [2, 6], [8, 10]]) == [[1, 6], [8, 10]]


def test_touching():
    assert merge_intervals([[1, 2], [2, 3]]) == [[1, 3]]


def test_empty():
    assert merge_intervals([]) == []


def test_unsorted():
    assert merge_intervals([[8, 10], [1, 3], [2, 6]]) == [[1, 6], [8, 10]]


def test_contained():
    assert merge_intervals([[1, 10], [2, 3], [4, 5]]) == [[1, 10]]


def test_disjoint():
    assert merge_intervals([[1, 2], [4, 5]]) == [[1, 2], [4, 5]]


def test_chain_touching():
    assert merge_intervals([[3, 4], [1, 2], [2, 3]]) == [[1, 4]]


def test_point_intervals():
    assert merge_intervals([[5, 5], [5, 5]]) == [[5, 5]]
