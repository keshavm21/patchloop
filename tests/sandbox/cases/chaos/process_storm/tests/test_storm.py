from solution import storm


def test_storm_is_capped():
    assert storm() < 64
