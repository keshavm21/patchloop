"""Measure the sandbox's per-run overhead: p50 and p95 wall time of a trivial passing run.

    python -m patchloop.sandbox.overhead --runs 20

Writes results/sandbox_overhead_<arch>.json, so the number quoted in the README traces to a file.
"""

import argparse
import json
import platform
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import docker

from .docker_runner import run_tests
from .limits import Limits

SOLUTION = "def answer():\n    return 42\n"
TEST = "from solution import answer\n\n\ndef test_answer():\n    assert answer() == 42\n"


def measure(runs: int, work_dir: Path, limits: Limits) -> list[float]:
    """Seconds per run_tests() call, container creation to removal; a warm-up run is dropped."""
    solution_dir, tests_dir = work_dir / "solution", work_dir / "tests"
    solution_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(exist_ok=True)
    (solution_dir / "solution.py").write_text(SOLUTION)
    (tests_dir / "test_answer.py").write_text(TEST)
    times = []
    for _ in range(runs + 1):
        start = time.perf_counter()
        result = run_tests(solution_dir, tests_dir, 1, limits)
        times.append(time.perf_counter() - start)
        if not result.passed:
            raise SystemExit(f"expected PASSED, got {result.status}: {result.problems}")
    return times[1:]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure the sandbox's per-run overhead.")
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--work-dir", type=Path, default=Path("runs/overhead"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    limits = Limits()
    times = measure(args.runs, args.work_dir, limits)
    client = docker.from_env()
    server = client.version()
    record = {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "what": "end-to-end run_tests() time for a trivial passing task with one test",
        "runs": len(times),
        "p50_s": round(statistics.median(times), 3),
        "p95_s": round(statistics.quantiles(times, n=20, method="inclusive")[-1], 3),
        "min_s": round(min(times), 3),
        "max_s": round(max(times), 3),
        "image_id": client.images.get(limits.image).id,
        "arch": platform.machine(),
        "docker": f"{server['Version']} ({server.get('Platform', {}).get('Name', 'unknown')})",
        "git_sha": _git("rev-parse", "HEAD"),
        # Only uncommitted changes to the measured code count, not edits to docs or results.
        "git_dirty": bool(_git("status", "--porcelain", "--", "src", "docker")),
    }
    out = args.out or Path("results") / f"sandbox_overhead_{record['arch']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2) + "\n")
    print(f"p50 {record['p50_s']} s, p95 {record['p95_s']} s over {record['runs']} runs -> {out}")


if __name__ == "__main__":
    main()
