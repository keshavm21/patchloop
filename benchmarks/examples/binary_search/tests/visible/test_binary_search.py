from solution import binary_search


def test_found_middle():
    assert binary_search([1, 3, 5, 7, 9], 5) == 2


def test_found_last():
    assert binary_search([1, 3, 5, 7, 9], 9) == 4


def test_missing():
    assert binary_search([1, 3, 5], 4) == -1
