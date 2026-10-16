from solution import binary_search


def test_found_middle():
    assert binary_search([1, 3, 5, 7, 9], 5) == 2


def test_found_last():
    assert binary_search([1, 3, 5, 7, 9], 9) == 4


def test_missing():
    assert binary_search([1, 3, 5], 4) == -1


def test_found_first():
    assert binary_search([1, 3, 5, 7, 9], 1) == 0


def test_empty():
    assert binary_search([], 1) == -1


def test_above_all():
    assert binary_search([1, 2, 3], 10) == -1


def test_below_all():
    assert binary_search([1, 2, 3], 0) == -1


def test_two_items():
    assert binary_search([4, 8], 8) == 1
