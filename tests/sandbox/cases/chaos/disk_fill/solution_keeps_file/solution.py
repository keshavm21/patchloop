"""Chaos: fills /tmp at import and leaves it full, so the runner has nowhere to write its
report; otherwise a correct answer."""

import os

with open("/tmp/fill.bin", "wb", buffering=0) as _f:
    for _ in range(1024):  # at most 1 GiB, in case the cap is missing
        try:
            _f.write(b"\0" * (1 << 20))
        except OSError:
            break


def second_largest(nums):
    uniq = sorted(set(nums))
    return uniq[-2] if len(uniq) >= 2 else None


assert os.path.getsize("/tmp/fill.bin") <= 64 << 20
