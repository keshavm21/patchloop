"""The dev/test split: a fixed-seed shuffle within each stratum (bug type), with dev slots
given out by largest remainder so the total is exactly round(fraction * N)."""

import math
import random
from collections import defaultdict

SEED = 20261017
DEV_FRACTION = 0.25


def stratified_split(
    strata: dict[str, str], *, fraction: float = DEV_FRACTION, seed: int = SEED
) -> dict[str, str]:
    """{task: stratum} -> {task: "dev" | "test"}."""
    groups: dict[str, list[str]] = defaultdict(list)
    for task, stratum in sorted(strata.items()):
        groups[stratum].append(task)
    target = math.floor(fraction * len(strata) + 0.5)
    quotas = {s: fraction * len(members) for s, members in groups.items()}
    dev_counts = {s: math.floor(q) for s, q in quotas.items()}
    by_remainder = sorted(groups, key=lambda s: (-(quotas[s] - dev_counts[s]), s))
    for s in by_remainder[: target - sum(dev_counts.values())]:
        dev_counts[s] += 1
    rng = random.Random(seed)
    split = {}
    for stratum in sorted(groups):
        members = groups[stratum][:]
        rng.shuffle(members)
        for i, task in enumerate(members):
            split[task] = "dev" if i < dev_counts[stratum] else "test"
    return split
