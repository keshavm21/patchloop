from solution import tmp_is_writable, writes_that_landed


def test_nothing_outside_tmp_is_writable():
    assert writes_that_landed() == []


def test_tmp_is_writable():
    assert tmp_is_writable()
