from solution import roman_to_int


def test_simple():
    assert roman_to_int("III") == 3


def test_subtractive():
    assert roman_to_int("IV") == 4


def test_mixed():
    assert roman_to_int("LVIII") == 58


def test_nine():
    assert roman_to_int("IX") == 9


def test_year():
    assert roman_to_int("MCMXCIV") == 1994


def test_max():
    assert roman_to_int("MMMCMXCIX") == 3999


def test_forty():
    assert roman_to_int("XL") == 40


def test_one():
    assert roman_to_int("I") == 1
