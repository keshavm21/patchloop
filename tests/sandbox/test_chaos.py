"""The chaos suite (§6.4): hostile fixtures on real Docker, no model. Each test runs a fixture
from cases/chaos/ and checks the sandbox contained it."""

import hashlib
import json
import re
from pathlib import Path

import pytest

from patchloop.models import Status
from patchloop.sandbox.limits import Limits
from patchloop.sandbox.parse import MAX_LOG

CASES = Path(__file__).parent / "cases"
CHAOS = CASES / "chaos"
SECOND_LARGEST_TESTS = CASES / "second_largest" / "tests"
GRACE_S = 5.0
CANARY = "pl-canary-3f9c1e7a5b"

# What the container's environment may hold besides the image's own variables: the four the
# runner sets, the hostname Docker adds, the shell's PWD/OLDPWD, and pytest's bookkeeping.
RUNNER_ENV = {"PYTHONPATH", "HOME", "PYTHONDONTWRITEBYTECODE", "PER_TEST_TIMEOUT"}
RUNNER_ENV |= {"HOSTNAME", "PWD", "OLDPWD"}


@pytest.fixture
def chaos(run_sandbox):
    """Run a chaos fixture: its solution/ folder against its own tests/, or the shared
    second_largest tests when it has none."""

    def _run(name: str, expected: int = 4, solution: str = "solution", **limits):
        tests = CHAOS / name / "tests"
        if not tests.exists():
            tests = SECOND_LARGEST_TESTS
        return run_sandbox(CHAOS / name / solution, tests, expected, **limits)

    return _run


def test_infinite_loop_is_killed_at_the_wall_limit(chaos):
    # The fixture disarms pytest-timeout's alarm, so only the host-side kill can stop it.
    result = chaos("infinite_loop", per_test_timeout_s=1, wall_timeout_s=4)
    assert result.status is Status.TIMEOUT
    assert result.timed_out
    assert result.duration_s < 4 + GRACE_S


def test_memory_blowup_is_contained(chaos, docker_client):
    result = chaos("memory_blowup")
    if result.status is Status.RUNTIME_ERROR:
        assert {f.exception for f in result.failures} == {"MemoryError"}
    else:
        assert result.status is Status.OOM
        assert result.oom
    assert docker_client.ping()


def test_process_storm_is_capped_by_the_pid_limit(chaos):
    # The fixture's own test asserts it started fewer children than the PID limit.
    result = chaos("process_storm", expected=1)
    assert result.status is Status.PASSED, result.failures
    assert result.duration_s < Limits().wall_timeout_s


def test_network_egress_fails(chaos):
    result = chaos("network_egress", expected=1)
    assert result.status is Status.PASSED, result.failures


def test_secret_hunting_finds_nothing(chaos, docker_client, monkeypatch):
    # Plant the canary where a leak through the host environment would carry it.
    monkeypatch.setenv("LLM_API_KEY", CANARY)
    result = chaos("secret_hunting", expected=1)
    assert result.status is Status.TESTS_FAILED
    assert CANARY not in result.model_dump_json()

    [loot_line] = re.findall(r"^@@LOOT (.*)$", result.log, re.MULTILINE)
    loot = json.loads(loot_line)
    image_env = docker_client.images.get(Limits().image).attrs["Config"]["Env"]
    allowed = RUNNER_ENV | {entry.split("=", 1)[0] for entry in image_env}
    assert {k for k in loot["env"] if not k.startswith("PYTEST_")} <= allowed
    assert loot["home"] == ["pytest.log"]  # HOME is /tmp, which holds only the runner's log
    assert all(value.startswith("<") for value in loot["readable"].values()), loot["readable"]
    assert loot["present"] == []


def test_writes_outside_tmp_fail(chaos):
    before = _snapshot(CHAOS / "write_outside_tmp")
    result = chaos("write_outside_tmp", expected=2)
    assert result.status is Status.PASSED, result.failures
    assert _snapshot(CHAOS / "write_outside_tmp") == before


def test_test_tampering_is_blocked(chaos):
    before = _snapshot(SECOND_LARGEST_TESTS)
    result = chaos("test_tampering")
    # The wrong answer (max) still fails every test, and every test still runs.
    assert result.status is Status.TESTS_FAILED
    assert (result.executed, result.num_failed) == (4, 4)
    assert _snapshot(SECOND_LARGEST_TESTS) == before


def test_disk_fill_stops_at_the_tmpfs_cap(chaos):
    # The fixture's own test asserts no more than the 64m cap landed.
    result = chaos("disk_fill", expected=1)
    assert result.status is Status.PASSED, result.failures


def test_disk_left_full_cannot_pass(chaos):
    # A correct answer that leaves /tmp full leaves the runner nowhere to write its report.
    result = chaos("disk_fill", solution="solution_keeps_file")
    assert result.status in (Status.RUNTIME_ERROR, Status.INTEGRITY_FAIL)
    assert result.executed == 0


def test_output_flood_is_truncated(chaos):
    result = chaos("output_flood")
    assert result.status is Status.PASSED, result.problems
    assert "flood" in result.log
    assert len(result.log) <= MAX_LOG + len("[truncated]... ")


def test_lingering_process_does_not_survive(chaos):
    # The fixture fails at import if its marker from an earlier run is still there.
    for _ in range(2):
        result = chaos("lingering_process")
        assert result.status is Status.PASSED, result.log
        assert result.duration_s < Limits().wall_timeout_s


def test_os_exit_at_import_is_not_success(chaos):
    result = chaos("fake_success_os_exit")
    assert result.status is Status.INTEGRITY_FAIL
    assert result.exit_code == 0
    assert result.problems == ["the JUnit report is missing or unreadable"]


def test_sys_exit_at_import_is_an_import_error(chaos):
    result = chaos("fake_success_sys_exit")
    assert result.status is Status.RUNTIME_ERROR
    assert result.exit_code in (2, 3)


def _snapshot(*folders: Path) -> dict[str, str]:
    """sha256 of every file under the folders, keyed by path."""
    return {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for folder in folders
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }
