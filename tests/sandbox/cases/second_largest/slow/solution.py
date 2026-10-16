import time


def second_largest(nums):
    """Correct, but far too slow."""
    time.sleep(3)
    uniq = sorted(set(nums))
    return uniq[-2] if len(uniq) >= 2 else None
