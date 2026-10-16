"""Chaos: fills /tmp, the only writable path, until the kernel refuses."""

import os

CHUNK = b"\0" * (1 << 20)


def fill(path="/tmp/fill.bin", keep=True):
    """Write 1 MiB chunks until a write fails; return the bytes that landed."""
    written = 0
    with open(path, "wb", buffering=0) as f:
        while written < (1 << 30):  # stop at 1 GiB in case the cap is missing
            try:
                written += f.write(CHUNK)
            except OSError:
                break
    if not keep:
        os.remove(path)
    return written
