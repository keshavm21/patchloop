"""Run a candidate's tests in a fresh, locked-down container."""

import contextlib
import functools
import time
from pathlib import Path

import docker
import docker.errors
import requests
from docker.models.containers import Container
from docker.types import LogConfig

from ..models import ExecutionResult, Status
from .limits import Limits
from .parse import parse_runner_output


class SandboxInfraError(RuntimeError):
    """Docker itself failed (daemon unreachable, image missing, API error). This is an infra
    error, never the candidate's fault."""


def run_tests(
    solution_dir: Path,
    tests_dir: Path,
    expected_tests: int,
    limits: Limits | None = None,
    client: docker.DockerClient | None = None,
) -> ExecutionResult:
    """Run the tests in `tests_dir` against the code in `solution_dir`, each in a fresh container.

    A SANDBOX_ERROR is retried once; if it repeats on the same code, it's an INTEGRITY_FAIL.
    """
    limits = limits or Limits()
    client = client or _default_client()
    result = _run_once(client, solution_dir, tests_dir, expected_tests, limits)
    if result.status is Status.SANDBOX_ERROR:
        result = _run_once(client, solution_dir, tests_dir, expected_tests, limits)
        if result.status is Status.SANDBOX_ERROR:
            result = result.model_copy(
                update={
                    "status": Status.INTEGRITY_FAIL,
                    "problems": [*result.problems, "the sandbox error repeated on the same code"],
                }
            )
    return result


@functools.cache
def _default_client() -> docker.DockerClient:
    try:
        return docker.from_env()
    except docker.errors.DockerException as e:
        raise SandboxInfraError(f"cannot reach Docker: {e}") from e


def _run_once(
    client: docker.DockerClient,
    solution_dir: Path,
    tests_dir: Path,
    expected_tests: int,
    limits: Limits,
) -> ExecutionResult:
    try:
        container = client.containers.create(
            limits.image,
            labels={"patchloop": "1"},
            network_mode="none",
            ipc_mode="none",  # no /dev/shm: /tmp stays the only writable path
            mem_limit=limits.memory,
            memswap_limit=limits.memory,  # equal to mem_limit: no swap
            nano_cpus=int(limits.cpus * 1e9),
            pids_limit=limits.pids,
            read_only=True,
            tmpfs={"/tmp": f"rw,noexec,nosuid,nodev,size={limits.tmpfs},mode=1777"},
            volumes={
                str(solution_dir.resolve()): {"bind": "/work/solution", "mode": "ro"},
                str(tests_dir.resolve()): {"bind": "/work/tests", "mode": "ro"},
            },
            environment={
                "PYTHONPATH": "/work/solution",
                "HOME": "/tmp",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PER_TEST_TIMEOUT": str(limits.per_test_timeout_s),
            },
            user="10001:10001",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            log_config=LogConfig(type=LogConfig.types.JSON, config={"max-size": "1m"}),
        )
        try:
            return _wait_and_collect(container, expected_tests, limits)
        finally:
            with contextlib.suppress(docker.errors.NotFound):
                container.remove(force=True)
    except (docker.errors.DockerException, requests.exceptions.RequestException) as e:
        raise SandboxInfraError(f"sandbox run failed: {e}") from e


def _wait_and_collect(container: Container, expected_tests: int, limits: Limits) -> ExecutionResult:
    timed_out = False
    start = time.monotonic()
    container.start()
    try:
        container.wait(timeout=limits.wall_timeout_s)
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
        timed_out = True
        with contextlib.suppress(docker.errors.APIError):  # it may have exited just now
            container.kill()
    duration_s = time.monotonic() - start
    container.reload()
    oom = bool(container.attrs["State"].get("OOMKilled", False))
    raw = container.logs(stdout=True, stderr=False)[: limits.max_read_bytes]
    return parse_runner_output(
        raw.decode("utf-8", errors="replace"),
        timed_out=timed_out,
        oom=oom,
        expected=expected_tests,
        duration_s=duration_s,
    )
