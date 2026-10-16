"""Real-Docker tests of the sandbox: `make sandbox-image`, then `make chaos`."""

import shutil
from pathlib import Path

import docker
import docker.errors
import pytest

from patchloop.models import ExecutionResult
from patchloop.sandbox.docker_runner import run_tests
from patchloop.sandbox.limits import Limits

# Code under cases/ is meant to run only inside the sandbox; never collect it on the host.
collect_ignore_glob = ["cases/*"]

RUNS = Path(__file__).resolve().parents[2] / "runs"


@pytest.fixture(scope="session", autouse=True)
def docker_client() -> docker.DockerClient:
    client = docker.from_env()
    image = Limits().image
    try:
        client.images.get(image)
    except docker.errors.ImageNotFound:
        pytest.exit(f"image {image!r} not found; run `make sandbox-image` first", returncode=1)
    return client


@pytest.fixture
def run_sandbox(docker_client):
    """run_tests() against real Docker, asserting that no labelled container is left behind."""

    def _run(solution: Path, tests: Path, expected: int, **limits) -> ExecutionResult:
        result = run_tests(solution, tests, expected, Limits(**limits), docker_client)
        leftovers = docker_client.containers.list(all=True, filters={"label": "patchloop"})
        assert not leftovers, f"containers left behind: {leftovers}"
        return result

    return _run


@pytest.fixture
def run_dir(request):
    """A scratch folder inside the project; Colima shares only the home folder with its VM."""
    path = RUNS / "pytest-sandbox" / request.node.name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)
