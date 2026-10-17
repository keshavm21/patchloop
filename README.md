# PatchLoop

A sandboxed, self-repairing coding agent. An LLM fixes buggy Python functions by running visible tests in a locked-down Docker container, reading the failures and patching until the tests pass. A benchmark harness measures how much each design choice helps, and a chaos suite shows the sandbox holds.

**Status:** early development. The sandbox, its chaos suite, the repair loop, two frozen benchmarks (HumanEvalFix, 162 tasks; MutBench, 200 mutated MBPP+ tasks) and the evaluation harness are in place. The full experiment matrix comes next.

See [docs/architecture.md](docs/architecture.md) for diagrams of the system, a sandbox run and the status rules.

Each sandbox run uses two fresh containers: a judge that runs the tests, and one that runs the candidate's code, reached only through a Unix socket that carries plain data. The candidate can't touch the tests or forge the verdict. Each container has no network, 512 MB of memory and no swap, 1 CPU, 64 processes, a read-only filesystem with a 64 MB `/tmp`, an unprivileged user, and per-test and wall-clock timeouts. A trivial passing run takes 0.60 s at the median and 0.77 s at p95, from container creation to removal (20 runs on Apple Silicon with Docker Desktop; [`results/sandbox_overhead_arm64.json`](results/sandbox_overhead_arm64.json)).

## Development setup

Requires Python 3.11+ and Docker.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # then add your model API key
ruff check .
make test                   # unit tests, no Docker needed
make sandbox-image          # build the sandbox image
make chaos                  # sandbox tests against real Docker
```

Repair one task, against any OpenAI-compatible API or a local Ollama:

```bash
patchloop solve benchmarks/examples/second_largest.json --config configs/full.yaml   # gpt-oss-20b on Groq
patchloop solve benchmarks/examples/second_largest.json --model <model-name>
patchloop solve benchmarks/examples/second_largest.json --model <model-name> --base-url http://localhost:11434/v1
patchloop replay runs/<date>/<task>/<run>/      # step through a finished run, with code diffs
```

Benchmarks are downloaded and built locally, never re-hosted. Only their manifests (dataset revision, file checksums, split) are committed, and setup checks the rebuilt files against them:

```bash
export HF_HOME=$PWD/.cache/hf
python -m patchloop.bench.setup humanevalfix     # bigcode/humanevalpack, pinned revision
python -m patchloop.bench.setup mutbench         # evalplus/mbppplus, pinned revision
patchloop eval --bench humanevalfix --split dev --config configs/single_shot.yaml --config configs/full.yaml
patchloop report results/humanevalfix-dev
```

Check that Python can reach Docker:

```bash
python -c "import docker; print(docker.from_env().ping())"    # prints True
```

The Docker SDK reads `DOCKER_HOST`, not the docker CLI's context. On Colima, set it first:

```bash
export DOCKER_HOST="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
```
