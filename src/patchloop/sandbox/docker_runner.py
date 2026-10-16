"""Run a candidate's tests in fresh, locked-down containers.

The tests never share a process or container with the candidate's code. A judge container
runs pytest against a stub `solution` module that forwards each call over a Unix socket to a
second container holding the candidate, so the verdict and the JUnit report stay out of the
candidate's reach. Both containers get every sandbox control.
"""

import contextlib
import functools
import time
from pathlib import Path

import docker
import docker.errors
import requests
from docker.models.containers import Container
from docker.models.volumes import Volume
from docker.types import LogConfig

from ..models import ExecutionResult, Status
from .limits import Limits
from .parse import parse_runner_output

LABELS = {"patchloop": "1"}


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
    """Run the tests in `tests_dir` against the code in `solution_dir` in fresh containers.

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
    """One run: a judge container that runs the tests against a stub, a separate container
    that runs the candidate, and a fresh volume holding the socket between them."""
    try:
        with contextlib.ExitStack() as cleanup:
            volume = client.volumes.create(labels=LABELS)
            cleanup.callback(_remove, volume)
            judge = _create(
                client,
                limits,
                volumes={
                    str(tests_dir.resolve()): {"bind": "/work/tests", "mode": "ro"},
                    volume.name: {"bind": "/run/pl", "mode": "rw"},
                },
                environment={
                    "PYTHONPATH": "/runner/judge:/runner",
                    "PER_TEST_TIMEOUT": str(limits.per_test_timeout_s),
                },
            )
            cleanup.callback(_remove, judge)
            candidate = _create(
                client,
                limits,
                volumes={
                    str(solution_dir.resolve()): {"bind": "/work/solution", "mode": "ro"},
                    volume.name: {"bind": "/run/pl", "mode": "ro"},
                },
                environment={"PYTHONPATH": "/work/solution"},
                entrypoint=["python", "/runner/worker.py"],
            )
            cleanup.callback(_remove, candidate)
            return _wait_and_collect(judge, candidate, expected_tests, limits)
    except (docker.errors.DockerException, requests.exceptions.RequestException) as e:
        raise SandboxInfraError(f"sandbox run failed: {e}") from e


def _create(
    client: docker.DockerClient,
    limits: Limits,
    *,
    volumes: dict,
    environment: dict[str, str],
    entrypoint: list[str] | None = None,
) -> Container:
    """A container with every control from the sandbox invariants."""
    return client.containers.create(
        limits.image,
        entrypoint=entrypoint,
        labels=LABELS,
        network_mode="none",
        ipc_mode="none",  # no /dev/shm: /tmp stays the only writable path
        mem_limit=limits.memory,
        memswap_limit=limits.memory,  # equal to mem_limit: no swap
        nano_cpus=int(limits.cpus * 1e9),
        pids_limit=limits.pids,
        read_only=True,
        tmpfs={"/tmp": f"rw,noexec,nosuid,nodev,size={limits.tmpfs},mode=1777"},
        volumes=volumes,
        environment={"HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1", **environment},
        user="10001:10001",
        cap_drop=["ALL"],
        security_opt=["no-new-privileges"],
        log_config=LogConfig(type=LogConfig.types.JSON, config={"max-size": "1m"}),
    )


def _remove(obj: Container | Volume) -> None:
    with contextlib.suppress(docker.errors.NotFound):
        obj.remove(force=True)


def _wait_and_collect(
    judge: Container, candidate: Container, expected_tests: int, limits: Limits
) -> ExecutionResult:
    timed_out = False
    start = time.monotonic()
    judge.start()
    candidate.start()
    try:
        judge.wait(timeout=limits.wall_timeout_s)
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
        timed_out = True
        with contextlib.suppress(docker.errors.APIError):  # it may have exited just now
            judge.kill()
    duration_s = time.monotonic() - start
    with contextlib.suppress(docker.errors.APIError):  # the judge is done; so is the candidate
        candidate.kill()
    judge.reload()
    candidate.reload()
    oom = any(c.attrs["State"].get("OOMKilled", False) for c in (judge, candidate))
    raw = judge.logs(stdout=True, stderr=False)[: limits.max_read_bytes]
    return parse_runner_output(
        raw.decode("utf-8", errors="replace"),
        timed_out=timed_out,
        oom=oom,
        expected=expected_tests,
        duration_s=duration_s,
    )
