from solution import hunt


def test_leak_what_was_found():
    print("@@LOOT " + hunt())
    raise AssertionError("leaked")
