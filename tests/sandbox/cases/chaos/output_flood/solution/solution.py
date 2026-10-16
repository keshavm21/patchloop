"""Chaos: a correct answer that prints in a tight loop, both to its own stdout (which pytest
captures) and through PID 1's stdout, which during the run is the runner's pytest log."""

import os

LINE = "flood " * 20 + "\n"


def _flood():
    for _ in range(20_000):  # ~2.4 MB per stream
        print(LINE, end="")
    try:
        fd = os.open("/proc/1/fd/1", os.O_WRONLY)
    except OSError:
        return
    data = (LINE * 1000).encode()
    for _ in range(100):  # ~12 MB into the runner's log
        os.write(fd, data)
    os.close(fd)


def second_largest(nums):
    _flood()
    uniq = sorted(set(nums))
    return uniq[-2] if len(uniq) >= 2 else None
