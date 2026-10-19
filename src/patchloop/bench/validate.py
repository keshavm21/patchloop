"""Benchmark validation (§8.3): a task is kept only if its reference solution passes the
visible and hidden tests in the sandbox (which also confirms the recorded test counts) and its
buggy starting code fails at least one hidden test."""

import hashlib
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from ..models import ExecutionResult, Status, Task
from ..sandbox.sandbox import Sandbox


@dataclass(frozen=True)
class Outcome:
    reason: str | None  # None: valid
    buggy_status: Status | None = None  # the buggy code's hidden run, for symptom labels


class ReferenceCache:
    """Reference runs keyed by (code, test files): mutants of one problem share them."""

    def __init__(self) -> None:
        self._results: dict[str, ExecutionResult] = {}
        self._lock = threading.Lock()

    def run(self, sandbox: Sandbox, code: str, tests: Path, expected: int) -> ExecutionResult:
        digest = hashlib.sha256(code.encode())
        for path in sorted(tests.rglob("*")):
            if path.is_file():
                digest.update(path.name.encode() + path.read_bytes())
        key = f"{digest.hexdigest()}-{expected}"
        with self._lock:
            if key in self._results:
                return self._results[key]
        result = sandbox.run(code, tests, expected)
        with self._lock:
            self._results[key] = result
        return result


def check_task(task: Task, sandbox: Sandbox, cache: ReferenceCache | None = None) -> Outcome:
    cache = cache or ReferenceCache()
    reference = (task.root / task.meta["reference"]).read_text()
    for name, tests, expected in [
        ("visible", task.visible_dir, task.expected_counts.visible),
        ("hidden", task.hidden_dir, task.expected_counts.hidden),
    ]:
        result = cache.run(sandbox, reference, tests, expected)
        if not result.passed:
            detail = "; ".join(result.problems) or ", ".join(
                f"{f.name.rsplit('::', 1)[-1]}: {f.exception}" for f in result.failures[:3]
            )
            return Outcome(f"reference fails the {name} tests ({result.status}: {detail})")
    buggy = sandbox.run(task.starting_code, task.hidden_dir, task.expected_counts.hidden)
    if buggy.status is Status.PASSED:
        return Outcome("buggy code passes every hidden test", buggy.status)
    if buggy.status is Status.INTEGRITY_FAIL:
        return Outcome(f"buggy code's hidden run is unreliable ({'; '.join(buggy.problems)})")
    return Outcome(None, buggy.status)


def check_all(
    paths: Iterable[Path],
    sandbox_for: Callable[[Path], Sandbox],
    *,
    workers: int = 3,
    progress: Callable[[str, str | None], None] = lambda slug, reason: None,
) -> dict[str, Outcome]:
    """{task file stem: Outcome}, checked `workers` at a time."""
    cache = ReferenceCache()

    def one(path: Path) -> tuple[str, Outcome]:
        outcome = check_task(Task.load(path), sandbox_for(path), cache)
        progress(path.stem, outcome.reason)
        return path.stem, outcome

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, sorted(paths)))
