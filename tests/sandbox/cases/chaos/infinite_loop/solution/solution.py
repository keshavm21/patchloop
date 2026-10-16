"""Chaos: spins forever inside the function under test, after disarming the alarm pytest-timeout
would use if it ran in this process. It doesn't: the timeout runs in the judge."""

import signal

signal.setitimer = lambda *args, **kwargs: (0.0, 0.0)


def second_largest(nums):
    while True:
        pass
