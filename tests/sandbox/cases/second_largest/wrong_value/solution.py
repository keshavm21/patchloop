def second_largest(nums):
    """Return the second-largest distinct value, or None if there isn't one."""
    uniq = sorted(set(nums))
    return uniq[-1] if len(uniq) >= 2 else None
