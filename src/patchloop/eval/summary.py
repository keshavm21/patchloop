"""The headline tables for results/REPORT.md, built from several results folders at once.

    python -m patchloop.eval.summary results/humanevalfix-test results/mutbench-test \
        [--extra results/mutbench-test-qwen] > results/summary.md

Every number is computed from the folders' records.jsonl; nothing is typed in by hand.
"""

import argparse
from pathlib import Path

from .metrics import by_config
from .report import COMPARISONS
from .runner import read_records
from .stats import paired_comparison, repair_rate_ci

ORDER = ["single_shot", "binary", "errors", "full", "full_5", "full_reflect"]


def _pct(x: float) -> str:
    return f"{100 * x:.1f}"


def _ci(records, config) -> str:
    ci = repair_rate_ci(records, config)
    return f"{_pct(ci.mean)} [{_pct(ci.low)}, {_pct(ci.high)}]" if ci else "–"


def _bench_name(records: list[dict]) -> str:
    return f"{records[0]['bench']} ({records[0]['split']})"


def headline(folders: list[Path]) -> list[str]:
    data = [(f, read_records(f)) for f in folders]
    configs = []
    for _, records in data:
        for name in by_config(records):
            if name not in configs and not name.endswith("_5"):
                configs.append(name)
    configs.sort(key=lambda c: ORDER.index(c) if c in ORDER else len(ORDER))
    benches = [_bench_name(records) for _, records in data]
    lines = [
        "| Config | "
        + " | ".join(f"{b} repair % [95% CI]" for b in benches)
        + " | "
        + " | ".join(f"{b} overfit %" for b in benches)
        + " | Tokens / task |",
        "|---|" + "---|" * (2 * len(benches) + 1),
    ]
    for config in configs:
        cells, overfit, tokens = [], [], []
        for _, records in data:
            metrics = by_config(records).get(config)
            cells.append(_ci(records, config) if metrics else "–")
            overfit.append(_pct(metrics.overfit_rate) if metrics else "–")
            if metrics:
                tokens.append(metrics.tokens_per_task)
        tok = f"{sum(tokens) / len(tokens):,.0f}" if tokens else "–"
        lines.append(
            f"| `{config}` | " + " | ".join(cells) + " | " + " | ".join(overfit) + f" | {tok} |"
        )
    return lines


def comparisons(folders: list[Path]) -> list[str]:
    lines = [
        "| Benchmark | a | b | Tasks | b − a, points [95% CI] | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for folder in folders:
        records = read_records(folder)
        names = set(by_config(records))
        for a, b in COMPARISONS:
            if a in names and b in names and (c := paired_comparison(records, a, b)):
                d = c.diff
                lines.append(
                    f"| {_bench_name(records)} | `{a}` | `{b}` | {c.tasks} | {100 * d.mean:+.1f} "
                    f"[{100 * d.low:+.1f}, {100 * d.high:+.1f}] | {c.verdict} |"
                )
    return lines


def success_at_k(folders: list[Path], config: str = "full_5") -> list[str]:
    rows = []
    for folder in folders:
        records = read_records(folder)
        m = by_config(records).get(config)
        if m:
            rows.append((_bench_name(records), m))
    if not rows:
        return []
    k_max = max(m.max_attempts for _, m in rows)
    lines = [
        f"| Benchmark (`{config}`) | " + " | ".join(f"k={k}" for k in range(1, k_max + 1)) + " |",
        "|---|" + "---|" * k_max,
    ]
    for bench, m in rows:
        lines.append(
            f"| {bench} | "
            + " | ".join(_pct(m.success_at_k.get(k, 0.0)) for k in range(1, k_max + 1))
            + " |"
        )
    return lines


def symptoms(folders: list[Path]) -> list[str]:
    lines = ["| Benchmark | Symptom | Runs | `single_shot` | `full` |", "|---|---|---|---|---|"]
    for folder in folders:
        records = read_records(folder)
        metrics = by_config(records)
        for key in ("symptom", "failure_symptoms"):
            single, full = metrics.get("single_shot"), metrics.get("full")
            if not single or not full or key not in full.breakdowns:
                continue
            for value, (runs, rate) in full.breakdowns[key].items():
                base = single.breakdowns.get(key, {}).get(value)
                lines.append(
                    f"| {_bench_name(records)} | {value} | {runs} | "
                    f"{_pct(base[1]) if base else '–'} | {_pct(rate)} |"
                )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folders", nargs="+", type=Path)
    parser.add_argument("--extra", action="append", type=Path, default=[], help="e.g. a model swap")
    args = parser.parse_args()
    out = ["## Headline results", "", *headline(args.folders), "", "## Comparisons", ""]
    out += comparisons(args.folders + args.extra)
    if sk := success_at_k(args.folders):
        out += ["", "## Success@k (attempts sweep)", "", *sk]
    out += ["", "## By failure symptom", "", *symptoms(args.folders)]
    for extra in args.extra:
        out += ["", f"## {_bench_name(read_records(extra))}, second model", "", *headline([extra])]
    print("\n".join(out))


if __name__ == "__main__":
    main()
