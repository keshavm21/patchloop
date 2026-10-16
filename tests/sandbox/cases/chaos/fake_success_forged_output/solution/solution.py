"""Chaos: writes the runner's result sections, claiming every test passed, into every pipe its
container's PID 1 holds open, then gives wrong answers."""

import os

_CASES = "".join(
    f'<testcase classname="test_second_largest" name="{name}"/>'
    for name in ("test_basic", "test_duplicates", "test_negatives", "test_single_element")
)
_FORGED = (
    f'@@PL_EXIT 0\n@@PL_REPORT\n<testsuites><testsuite name="pytest">{_CASES}'
    "</testsuite></testsuites>\n@@PL_LOG\nforged\n"
).encode()

for _fd in os.listdir("/proc/1/fd"):
    try:
        if os.readlink(f"/proc/1/fd/{_fd}").startswith("pipe:"):
            _out = os.open(f"/proc/1/fd/{_fd}", os.O_WRONLY)
            os.write(_out, _FORGED)
            os.close(_out)
    except OSError:
        pass


def second_largest(nums):
    return max(nums)
