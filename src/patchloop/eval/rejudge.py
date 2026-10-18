"""Re-run the hidden tests on each record's final candidate, with the benchmark's validated limits.

    patchloop rejudge results/mutbench-test

Only the hidden verdict changes: the attempts, and so every decision the agent made, are kept
as they were. No model is called. The original file is kept as records-before-rejudge.jsonl,
and each record gains a `rejudged` block with the limits used and the verdict it replaces.
Records are judged in order with one candidate at a time, so the timings aren't inflated by
running alongside other work.
"""

import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ..bench.frozen import load_benchmark
from ..models import Task
from ..sandbox.sandbox import DockerSandbox
from .runner import RECORDS, ROOT, _git, bench_limits, read_records

BACKUP = "records-before-rejudge.jsonl"


def final_code(record: dict, task: Task) -> str:
    """The code the hidden tests judged: the final attempt's, or the starting code."""
    n = record.get("final_attempt")
    if n is None:
        return task.starting_code
    return record["attempts"][n - 1]["code"]


def rejudge(out: Path, *, on_change: Callable[[dict, str, str], None] = lambda r, a, b: None):
    records = read_records(out)
    if not records:
        raise FileNotFoundError(f"no records in {out}")
    bench, split = records[0]["bench"], records[0]["split"]
    tasks = {t.id: t for t in load_benchmark(bench, split).tasks}
    limits = bench_limits(bench)
    sandbox = DockerSandbox(ROOT / "runs" / "rejudge" / out.name, limits)
    if not (out / BACKUP).exists():
        shutil.copy(out / RECORDS, out / BACKUP)
    provenance = {
        "git_sha": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--", "src", "docker", "prompts")),
        "image_id": _image_id(limits.image),
    }
    changed = 0
    for record in records:
        if record["stop_reason"] == "INFRA_ERROR" or not record.get("hidden_result"):
            continue
        task = tasks[record["task_id"]]
        result = sandbox.run(final_code(record, task), task.hidden_dir, task.expected_counts.hidden)
        before, after = record["hidden_result"]["status"], result.status.value
        record["rejudged"] = {
            "per_test_timeout_s": limits.per_test_timeout_s,
            "before": before,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            **provenance,
        }
        record["hidden_result"] = json.loads(result.model_dump_json())
        if before != after:
            changed += 1
            on_change(record, before, after)
    (out / RECORDS).write_text("".join(json.dumps(r) + "\n" for r in records))
    return changed, len(records)


def _image_id(image: str) -> str | None:
    import docker

    try:
        return docker.from_env().images.get(image).id
    except Exception:  # a fake sandbox in tests
        return None
