"""A sandbox for unit tests: maps code to canned results, so no Docker is needed."""

from collections.abc import Callable
from pathlib import Path

from ..models import ExecutionResult


class FakeSandbox:
    def __init__(
        self,
        results: dict[str, ExecutionResult] | Callable[[str, Path], ExecutionResult],
        *,
        default: ExecutionResult | None = None,
    ) -> None:
        self.results = results
        self.default = default
        self.runs: list[tuple[str, Path]] = []  # (code, tests_dir) for every run

    def run(self, code: str, tests_dir: Path, expected_tests: int) -> ExecutionResult:
        self.runs.append((code, tests_dir))
        if callable(self.results):
            return self.results(code, tests_dir)
        if code in self.results:
            return self.results[code]
        if self.default is None:
            raise KeyError(f"FakeSandbox has no result for this code:\n{code}")
        return self.default
