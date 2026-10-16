from solution import fill


def test_fill_stops_at_the_tmpfs_cap():
    assert fill(keep=False) <= 64 << 20
