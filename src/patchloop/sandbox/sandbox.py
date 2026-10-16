"""The sandbox as the loop sees it: run some code against a test folder, get a result."""

import hashlib
from pathlib import Path
from typing import Protocol

import docker

from ..models import ExecutionResult
from .docker_runner import run_tests
from .limits import Limits


class Sandbox(Protocol):
    def run(self, code: str, tests_dir: Path, expected_tests: int) -> ExecutionResult: ...


class DockerSandbox:
    """Writes each candidate to its own folder under `work_dir`, then runs it with run_tests().

    Keep `work_dir` inside the project (under runs/): Colima shares only the home folder with
    its VM, so a folder elsewhere shows up empty inside the container.
    """

    def __init__(
        self,
        work_dir: Path,
        limits: Limits | None = None,
        client: docker.DockerClient | None = None,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.limits = limits or Limits()
        self.client = client

    def run(self, code: str, tests_dir: Path, expected_tests: int) -> ExecutionResult:
        digest = hashlib.sha256(code.encode()).hexdigest()[:12]
        solution_dir = self.work_dir / "candidates" / digest
        solution_dir.mkdir(parents=True, exist_ok=True)
        (solution_dir / "solution.py").write_text(code)
        return run_tests(solution_dir, tests_dir, expected_tests, self.limits, self.client)
