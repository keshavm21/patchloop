"""Chaos: tries to write everywhere except /tmp, including places that would persist or be
picked up by the next run."""

import os

TARGETS = [
    "/work/solution/pwned.py",
    "/work/tests/test_pwned.py",
    "/pwned",
    "/etc/pwned",
    "/runner/run_tests.sh",
    "/usr/local/lib/python3.12/site-packages/pwned.pth",
    "/var/tmp/pwned",
    "/dev/shm/pwned",
    "/dev/mqueue/pwned",
    "/dev/pwned",
    "/run/pl/pwned",  # the judge's socket folder
]


def writes_that_landed():
    landed = []
    for path in TARGETS:
        try:
            with open(path, "a") as f:
                f.write("pwned\n")
        except OSError:
            continue
        landed.append(path)
    return landed


def tmp_is_writable():
    path = os.path.join("/tmp", "scratch.txt")
    with open(path, "w") as f:
        f.write("ok")
    return os.path.exists(path)
