def second_largest(nums):
    """Return the second-largest distinct value in nums, or None if there isn't one."""
    uniq = sorted(set(nums))
    return uniq[-2] if len(uniq) >= 2 else None
