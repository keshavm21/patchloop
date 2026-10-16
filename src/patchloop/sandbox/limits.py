"""Resource limits for one sandbox run. Never loosen them to make a run pass."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    image: str = "patchloop-sandbox"
    memory: str = "512m"  # also the swap limit, so there is no swap
    cpus: float = 1.0
    pids: int = 64
    tmpfs: str = "64m"  # the only writable path, /tmp
    per_test_timeout_s: float = 5.0
    wall_timeout_s: float = 30.0  # host-side kill
    max_read_bytes: int = 256 * 1024  # of container output read back on the host
