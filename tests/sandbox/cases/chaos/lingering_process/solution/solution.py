"""Chaos: a correct answer that leaves a detached background process running, and checks at
import that nothing from an earlier run survived."""

import os
import time

MARKER = "/tmp/lingering.pid"

if os.path.exists(MARKER):
    raise RuntimeError("state from an earlier run survived")

if os.fork() == 0:
    os.setsid()
    if os.fork() == 0:  # double fork: reparented, outside pytest's process tree
        with open(MARKER, "w") as f:
            f.write(str(os.getpid()))
        while True:
            time.sleep(1)
    os._exit(0)


def second_largest(nums):
    uniq = sorted(set(nums))
    return uniq[-2] if len(uniq) >= 2 else None
