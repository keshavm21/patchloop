# PatchLoop

A sandboxed, self-repairing coding agent. An LLM fixes buggy Python functions by running visible tests in a locked-down Docker container, reading the failures and patching until the tests pass. A benchmark harness measures how much each design choice helps, and a chaos suite shows the sandbox holds.

**Status:** early development. The project skeleton and CI are in place; the sandbox, agent loop and benchmarks come next.

## Development setup

Requires Python 3.11+ and Docker.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # then add your model API key
ruff check .
make test
```

Check that Python can reach Docker:

```bash
python -c "import docker; print(docker.from_env().ping())"    # prints True
```

The Docker SDK reads `DOCKER_HOST`, not the docker CLI's context. On Colima, set it first:

```bash
export DOCKER_HOST="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
```
