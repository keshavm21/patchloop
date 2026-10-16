"""Chaos: finds the socket to the judge and floods it with 20 MB of junk without a newline,
before the worker can say hello."""

import os

for _fd in os.listdir("/proc/self/fd"):
    try:
        if os.readlink(f"/proc/self/fd/{_fd}").startswith("socket:"):
            for _ in range(20):
                os.write(int(_fd), b"x" * (1 << 20))
    except OSError:
        pass


def second_largest(nums):
    uniq = sorted(set(nums))
    return uniq[-2] if len(uniq) >= 2 else None
