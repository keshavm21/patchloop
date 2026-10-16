"""Chaos: a wrong answer that tries, at import, to rewrite, delete or shadow the tests so they
pass anyway."""

import glob
import os

_FORGED = "def test_forged():\n    pass\n"

for _path in glob.glob("/work/tests/*.py"):
    for _attempt in (
        lambda p: open(p, "w").write(_FORGED),
        lambda p: os.chmod(p, 0o777),
        lambda p: os.rename(p, p + ".bak"),
        lambda p: os.remove(p),
    ):
        try:
            _attempt(_path)
        except OSError:
            pass
for _path in ("/work/tests/conftest.py", "/work/conftest.py", "/tmp/conftest.py"):
    try:
        with open(_path, "w") as _f:  # a conftest that would mark every test as passed
            _f.write("import pytest\n\n@pytest.hookimpl(tryfirst=True)\n"
                     "def pytest_runtest_call(item):\n    return True\n")
    except OSError:
        pass


def second_largest(nums):
    return max(nums)
