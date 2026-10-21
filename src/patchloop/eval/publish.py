"""Write results/REPORT.md and the README's results section from the results folders.

    python -m patchloop.eval.publish

Both come from templates (results/REPORT.template.md, results/README_results.template.md) whose
$placeholders are filled with numbers computed here from records.jsonl and
results/error_analysis.json. Nothing is typed in by hand, and a value that has no data yet
renders as "pending", so re-running after more repeats land updates every number at once.
"""

import json
import re
from collections import Counter
from pathlib import Path
from string import Template

from . import inject
from .metrics import by_config
from .runner import ROOT, report_records
from .stats import paired_comparison, repair_rate_ci
from .summary import comparisons, folder_comparisons, headline, success_at_k, symptoms

RESULTS = ROOT / "results"
FOLDERS = {"hef": "humanevalfix-test", "mb": "mutbench-test", "qwen": "mutbench-test-qwen"}
MAIN = ["hef", "mb"]
README = ROOT / "README.md"
# The generated block, or just the opening marker the first time (never "to end of file").
MARKER = re.compile(r"<!-- RESULTS -->(?:.*?<!-- /RESULTS -->)?", re.DOTALL)
PENDING = "pending"


class Values(dict):
    def __missing__(self, key: str) -> str:
        return PENDING


def _pct(x: float) -> str:
    return f"{100 * x:.1f}"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def collect() -> Values:
    v = Values()
    for alias, folder in FOLDERS.items():
        path = RESULTS / folder
        if not (path / "records.jsonl").exists():
            continue
        records = report_records(path)
        v[f"{alias}_bench"] = f"{records[0]['bench']} ({records[0]['split']})"
        v[f"{alias}_model"] = records[0]["provenance"]["model"]
        v[f"{alias}_shas"] = ", ".join(
            sorted({f"`{r['provenance']['git_sha'][:7]}`" for r in records})
        )
        for name, m in by_config(records).items():
            base = name.removesuffix("_qwen")
            ci = repair_rate_ci(records, name)
            v[f"{alias}_{base}"] = f"{_pct(ci.mean)} [{_pct(ci.low)}, {_pct(ci.high)}]"
            v[f"{alias}_{base}_rate"] = _pct(ci.mean)
            v[f"{alias}_{base}_n"] = f"{m.tasks} × {m.repeats}"
            v[f"{alias}_{base}_tasks"] = str(m.tasks)
            v[f"{alias}_{base}_repeats"] = str(m.repeats)
            v[f"{alias}_{base}_overfit"] = _pct(m.overfit_rate)
            v[f"{alias}_{base}_tokens"] = f"{m.tokens_per_task:,.0f}"
            if m.cut_off_rate is not None:
                v[f"{alias}_{base}_cutoff"] = _pct(m.cut_off_rate)
            v[f"{alias}_{base}_quarantined"] = str(m.quarantined)
            for k, rate in m.success_at_k.items():
                v[f"{alias}_{base}_k{k}"] = _pct(rate)
        for a, b, c in folder_comparisons(records):
            key = f"{alias}_{a.removesuffix('_qwen')}_vs_{b.removesuffix('_qwen')}"
            d = c.diff
            v[key] = f"{100 * d.mean:+.1f} [{100 * d.low:+.1f}, {100 * d.high:+.1f}]"
            v[f"{key}_verdict"] = c.verdict.replace("_qwen", "")
        _gains(v, alias, records)
    _error_analysis(v)
    _safety(v)
    v["table_headline"] = "\n".join(headline([RESULTS / FOLDERS[a] for a in MAIN if a in _have()]))
    v["table_comparisons"] = "\n".join(
        comparisons([RESULTS / f for a, f in FOLDERS.items() if a in _have()])
    )
    v["table_symptoms"] = "\n".join(symptoms([RESULTS / FOLDERS[a] for a in MAIN if a in _have()]))
    sk = success_at_k([RESULTS / FOLDERS[a] for a in MAIN if a in _have()])
    v["table_success_at_k"] = "\n".join(sk) if sk else "The attempts sweep is still running."
    if "qwen" in _have():
        v["table_qwen"] = "\n".join(headline([RESULTS / FOLDERS["qwen"]]))
    return v


def _have() -> set[str]:
    return {a for a, f in FOLDERS.items() if (RESULTS / f / "records.jsonl").exists()}


def _gains(v: Values, alias: str, records: list[dict]) -> None:
    """Tasks only the loop solved, by how the single attempt had failed: a format failure the
    loop recovered from, or a wrong answer it fixed from test feedback."""
    names = set(by_config(records))
    suffix = "_qwen" if "full_qwen" in names else ""
    single = {
        (r["task_id"], r["repeat"]): r for r in records if r["config"] == "single_shot" + suffix
    }
    full = {(r["task_id"], r["repeat"]): r for r in records if r["config"] == "full" + suffix}

    def ok(r):
        return (r.get("hidden_result") or {}).get("status") == "PASSED"

    keys = [k for k in full if k in single and full[k]["stop_reason"] != "INFRA_ERROR"]
    gained = [k for k in keys if ok(full[k]) and not ok(single[k])]
    how = Counter(
        single[k]["attempts"][0]["result"]["status"] for k in gained if single[k]["attempts"]
    )
    v[f"{alias}_gained"] = str(len(gained))
    v[f"{alias}_gained_format"] = str(how["PARSE_FAILED"])
    v[f"{alias}_gained_feedback"] = str(len(gained) - how["PARSE_FAILED"])
    v[f"{alias}_lost"] = str(sum(ok(single[k]) and not ok(full[k]) for k in keys))


INJECT = RESULTS / "injectbench-test"
CLEAN = RESULTS / "mutbench-dev-defense"
LADDER = ["d0", "d1", "d2", "d3"]


def _safety(v: Values) -> None:
    """The safety table (§8.8 C): policy check, chaos suite, canary scans, InjectBench, and the
    clean-task cost of the defenses. Each part stays "pending" until its data exists."""
    measured = RESULTS / "policy_check.json"
    if measured.exists():
        data = json.loads(measured.read_text())
        fps = data["false_positives"]
        v["pol_total"] = str(sum(b["references"] for b in fps.values()))
        v["pol_fp"] = str(sum(b["blocked"] for b in fps.values()))
        v["pol_fp_tasks"] = ", ".join(
            f"{b} `{slug}`"
            for b, d in fps.items()
            for slug in d["findings"]
            if d["findings"][slug]["blocked"]
        )
        v["pol_chaos_blocked"] = str(data["chaos"]["blocked"])
        v["pol_chaos_total"] = str(data["chaos"]["fixtures"])
        if data.get("chaos_suite"):
            v["chaos_passed"] = str(data["chaos_suite"]["passed"])
            v["chaos_tests"] = str(data["chaos_suite"]["tests"])
    scans = [json.loads(f.read_text()) for f in sorted(RESULTS.glob("*/canary_scan.json"))]
    if scans:
        v["canary_hits"] = str(sum(len(x["hits"]) for x in scans))
        v["canary_files"] = f"{sum(x['files_scanned'] for x in scans):,}"
        v["canary_folders"] = str(len(scans))
    if (INJECT / "records.jsonl").exists():
        try:
            starting = inject.starting_codes()
        except Exception:  # the generated tasks are missing: python -m patchloop.bench.injectbench
            starting = None
        if starting:
            records = report_records(INJECT)
            rows = inject.by_config(records, starting)
            for level in LADDER:
                row = rows.get(f"defense_{level}")
                if not row:
                    continue
                v[f"inj_{level}_attempted"] = _pct(row["attempted_rate"])
                v[f"inj_{level}_attempted_n"] = f"{row['attempted']} of {row['runs']}"
                v[f"inj_{level}_solved"] = _pct(row["solved_rate"])
                v[f"inj_{level}_blocked"] = str(row["blocked"])
                v[f"inj_{level}_violations"] = str(row["effective_violations"])
            per = inject.by_channel(records, starting)
            cells = [(ch, row) for chans in per.values() for ch, row in chans.items()]
            for key, pick in (
                ("tt", lambda ch: ch == "task_text"),
                ("other", lambda ch: ch != "task_text"),
            ):
                v[f"inj_{key}_attempted"] = str(sum(r["attempted"] for ch, r in cells if pick(ch)))
                v[f"inj_{key}_runs"] = str(sum(r["runs"] for ch, r in cells if pick(ch)))
            v["inj_violations"] = str(sum(r["effective_violations"] for r in rows.values()))
            v["inj_runs"] = str(sum(r["runs"] for r in rows.values()))
            v["table_inject"] = "\n".join(_inject_table(records, starting))
    if (CLEAN / "records.jsonl").exists():
        records = report_records(CLEAN)
        names = set(by_config(records))
        if {"defense_d0", "defense_d3"} <= names:
            for level in ("d0", "d3"):
                ci = repair_rate_ci(records, f"defense_{level}")
                v[f"clean_{level}"] = f"{_pct(ci.mean)} [{_pct(ci.low)}, {_pct(ci.high)}]"
                v[f"clean_{level}_rate"] = _pct(ci.mean)
            c = paired_comparison(records, "defense_d0", "defense_d3")
            d = c.diff
            v["clean_tasks"] = str(c.tasks)
            v["clean_diff"] = f"{100 * d.mean:+.1f} [{100 * d.low:+.1f}, {100 * d.high:+.1f}]"
            v["clean_verdict"] = c.verdict.replace("defense_", "").replace("`d3`", "D3")


def _inject_table(records: list[dict], starting: dict[str, str]) -> list[str]:
    channels = inject.by_channel(records, starting)
    names = sorted({ch for per in channels.values() for ch in per})
    lines = [
        "| Defense | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    for level in LADDER:
        per = channels.get(f"defense_{level}")
        if not per:
            continue
        cells = [
            f"{per[ch]['attempted']} / {per[ch]['runs']}" if ch in per else "–" for ch in names
        ]
        lines.append(f"| {level.upper()} | " + " | ".join(cells) + " |")
    return lines


def _error_analysis(v: Values) -> None:
    path = RESULTS / "error_analysis.json"
    if not path.exists():
        return
    labels = json.loads(path.read_text())["labels"]
    counts = Counter(label["category"] for label in labels)
    v["ea_total"] = str(len(labels))
    for category, n in counts.items():
        v[f"ea_{_slug(category)}"] = str(n)
    v["table_error_analysis"] = "\n".join(
        ["| Category | Failures |", "|---|---|"]
        + [f"| {category} | {n} |" for category, n in counts.most_common()]
    )


def render(template: Path, values: Values) -> str:
    return Template(template.read_text()).substitute(values)


def main() -> None:
    values = collect()
    report = render(RESULTS / "REPORT.template.md", values)
    (RESULTS / "REPORT.md").write_text(report)
    section = render(RESULTS / "README_results.template.md", values).strip()
    readme = README.read_text()
    block = f"<!-- RESULTS -->\n{section}\n<!-- /RESULTS -->"
    README.write_text(MARKER.sub(lambda _: block, readme, count=1))
    pending = sorted(
        set(re.findall(r"\$\{?(\w+)", (RESULTS / "REPORT.template.md").read_text())) - set(values)
    )
    print(f"wrote {RESULTS / 'REPORT.md'} and the README results section")
    if pending:
        print("pending (no data yet):", ", ".join(pending))


if __name__ == "__main__":
    main()
