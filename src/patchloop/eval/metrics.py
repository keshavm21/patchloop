"""Metrics (§8.5) over records.jsonl. Infra errors are excluded from every agent metric and
counted separately; a triple whose every record is an infra error is "quarantined"."""

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

INFRA = "INFRA_ERROR"


@dataclass
class ConfigMetrics:
    config: str
    model: str
    runs: int
    tasks: int
    repeats: int
    max_attempts: int
    repair_rate: float
    success_at_k: dict[int, float]
    attempts_to_success: float | None
    overfit_rate: float
    regression_rate: float | None
    cut_off_rate: float | None  # attempts whose reply hit max_output_tokens (None: not recorded)
    tokens_per_task: float
    cost_per_task: float | None  # None unless every run had a known cost
    seconds_per_task: float
    model_seconds_per_task: float
    retry_wait_per_task: float  # time spent waiting on the provider's rate limits
    cached_call_share: float  # model calls served from the cache (paired configs share attempt 1)
    sandbox_p50_s: float | None
    sandbox_p95_s: float | None
    stop_reasons: dict[str, int]
    infra_retried: int  # infra errors on triples that later finished
    quarantined: int  # triples with nothing but infra errors
    breakdowns: dict[str, dict[str, tuple[int, float]]] = field(default_factory=dict)


def finished(records: list[dict]) -> list[dict]:
    """The latest non-infra record per (task, config, repeat)."""
    latest = {}
    for r in records:
        if r["stop_reason"] != INFRA:
            latest[(r["task_id"], r["config"], r["repeat"])] = r
    return list(latest.values())


def by_config(
    records: list[dict], breakdown_keys=("bug_type", "failure_symptoms", "operator", "symptom")
):
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[r["config"]].append(r)
    return {name: config_metrics(name, rs, breakdown_keys) for name, rs in sorted(groups.items())}


def config_metrics(name: str, records: list[dict], breakdown_keys) -> ConfigMetrics:
    runs = finished(records)
    done = {(r["task_id"], r["repeat"]) for r in runs}
    infra_keys = [(r["task_id"], r["repeat"]) for r in records if r["stop_reason"] == INFRA]
    retried = sum(k in done for k in infra_keys)
    quarantined = len({k for k in infra_keys if k not in done})
    max_attempts = max((r["max_attempts"] for r in runs), default=0)
    solved = [_solved(r) for r in runs]
    n = len(runs)

    later_attempts = [a for r in runs for a in r["attempts"] if a["n"] > 1 and a["ran"]]
    recorded = [a for r in runs for a in r["attempts"] if a.get("finish_reason")]
    sandbox_times = sorted(
        a["result"]["duration_s"] for r in runs for a in r["attempts"] if a["ran"]
    )
    costs = [r["usage"].get("cost_usd") for r in runs]

    breakdowns = {}
    for key in breakdown_keys:
        values = defaultdict(list)
        for r, ok in zip(runs, solved, strict=True):
            if key in r.get("meta", {}):
                values[str(r["meta"][key])].append(ok)
        if values:
            breakdowns[key] = {v: (len(oks), _mean(oks)) for v, oks in sorted(values.items())}

    return ConfigMetrics(
        config=name,
        model=runs[0]["model"] if runs else "",
        runs=n,
        tasks=len({r["task_id"] for r in runs}),
        repeats=len({r["repeat"] for r in runs}),
        max_attempts=max_attempts,
        repair_rate=_mean(solved),
        success_at_k={
            k: _mean(
                [ok and (r["final_attempt"] or 0) <= k for r, ok in zip(runs, solved, strict=True)]
            )
            for k in range(1, max_attempts + 1)
        },
        attempts_to_success=(
            statistics.mean(r["final_attempt"] for r, ok in zip(runs, solved, strict=True) if ok)
            if any(solved)
            else None
        ),
        overfit_rate=_mean(
            [r["stop_reason"] == "SOLVED" and not ok for r, ok in zip(runs, solved, strict=True)]
        ),
        regression_rate=_mean([bool(a["regressions"]) for a in later_attempts])
        if later_attempts
        else None,
        cut_off_rate=_mean([a["finish_reason"] == "length" for a in recorded])
        if recorded
        else None,
        tokens_per_task=_mean([_tokens(r["usage"]) for r in runs]),
        cost_per_task=_mean(costs) if costs and all(c is not None for c in costs) else None,
        seconds_per_task=_mean([r["duration_s"] for r in runs]),
        model_seconds_per_task=_mean([r["usage"]["latency_s"] for r in runs]),
        retry_wait_per_task=_mean([r["usage"].get("retry_wait_s", 0.0) for r in runs]),
        cached_call_share=(
            sum(r["usage"]["cached_calls"] for r in runs) / calls
            if (calls := sum(r["usage"]["calls"] for r in runs))
            else 0.0
        ),
        sandbox_p50_s=_quantile(sandbox_times, 0.5),
        sandbox_p95_s=_quantile(sandbox_times, 0.95),
        stop_reasons=dict(Counter(r["stop_reason"] for r in runs).most_common()),
        infra_retried=retried,
        quarantined=quarantined,
        breakdowns=breakdowns,
    )


def _solved(record: dict) -> bool:
    hidden = record.get("hidden_result")
    return bool(hidden) and hidden["status"] == "PASSED"


def _tokens(usage: dict) -> int:
    return usage["input_tokens"] + usage["output_tokens"]


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _quantile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    return statistics.quantiles(sorted_values, n=100, method="inclusive")[round(q * 100) - 1]
