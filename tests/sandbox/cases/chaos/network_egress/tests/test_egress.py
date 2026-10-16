from solution import egress_attempts


def test_no_way_out():
    assert egress_attempts() == []
