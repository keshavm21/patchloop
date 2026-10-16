def merge_intervals(intervals):
    """Merge overlapping or touching closed intervals [start, end].

    Returns a new list of merged intervals sorted by start. The input is not modified.
    """
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged
