"""Chaos: forks in a loop and leaves every child running."""

import os
import time


def storm(limit=1000):
    """Fork until the kernel refuses; return how many children started."""
    started = 0
    for _ in range(limit):
        try:
            pid = os.fork()
        except OSError:
            break
        if pid == 0:  # child: hold its PID slot, never clean up
            time.sleep(3600)
            os._exit(0)
        started += 1
    return started
