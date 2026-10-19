"""Confidence intervals by bootstrap over tasks (§8.6).

Each task's solve rate is averaged over its repeats first, so repeats reduce noise without
counting as extra tasks. Comparisons are paired: both configs on the same tasks, and the
tasks are resampled together.
"""

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from .metrics import finished

N_RESAMPLES = 10_000
SEED = 0


@dataclass(frozen=True)
class Interval:
    mean: float
    low: float
    high: float

    @property
    def includes_zero(self) -> bool:
        return self.low <= 0.0 <= self.high


@dataclass(frozen=True)
class Comparison:
    a: str
    b: str
    tasks: int
    diff: Interval  # b - a, in solve-rate points (0..1)

    @property
    def verdict(self) -> str:
        if self.diff.includes_zero:
            return "no clear difference"
        return f"`{self.b}` better" if self.diff.mean > 0 else f"`{self.a}` better"


def per_task_rates(records: list[dict], config: str) -> dict[str, float]:
    """{task: share of its finished repeats whose hidden tests pass}."""
    outcomes = defaultdict(list)
    for r in finished(records):
        if r["config"] == config:
            hidden = r.get("hidden_result") or {}
            outcomes[r["task_id"]].append(hidden.get("status") == "PASSED")
    return {task: float(np.mean(oks)) for task, oks in outcomes.items()}


def bootstrap_mean(values: np.ndarray, *, n: int = N_RESAMPLES, seed: int = SEED) -> Interval:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(n, len(values)))
    means = values[idx].mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return Interval(float(values.mean()), float(low), float(high))


def repair_rate_ci(records: list[dict], config: str) -> Interval | None:
    rates = per_task_rates(records, config)
    if not rates:
        return None
    return bootstrap_mean(np.array([rates[t] for t in sorted(rates)]))


def paired_comparison(records: list[dict], a: str, b: str) -> Comparison | None:
    """b - a over the tasks both configs finished, with a paired 95% bootstrap interval."""
    ra, rb = per_task_rates(records, a), per_task_rates(records, b)
    tasks = sorted(set(ra) & set(rb))
    if not tasks:
        return None
    diffs = np.array([rb[t] - ra[t] for t in tasks])
    return Comparison(a, b, len(tasks), bootstrap_mean(diffs))
