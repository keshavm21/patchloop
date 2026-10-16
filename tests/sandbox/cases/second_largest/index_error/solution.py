def second_largest(nums):
    """Return the second-largest distinct value, or None if there isn't one."""
    uniq = sorted(set(nums))
    return uniq[-2]
