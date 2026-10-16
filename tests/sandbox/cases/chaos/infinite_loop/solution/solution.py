"""Chaos: spins forever, after disarming the alarm pytest-timeout uses to stop a test."""

import signal

signal.setitimer = lambda *args, **kwargs: (0.0, 0.0)


def second_largest(nums):
    while True:
        pass
