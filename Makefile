# Use the project venv when it exists, so targets work without activating it.
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: sandbox-image test chaos demo clean-containers

sandbox-image:
	docker build -t patchloop-sandbox -f docker/sandbox.Dockerfile docker/

test:
	$(PYTHON) -m pytest tests/unit -q

chaos:
	$(PYTHON) -m pytest tests/sandbox -q

demo:
	$(PYTHON) -m patchloop solve benchmarks/examples/second_largest.json --llm replay

clean-containers:
	@ids="$$(docker ps -aq --filter label=patchloop)"; \
	if [ -n "$$ids" ]; then docker rm -f $$ids; else echo "no patchloop containers"; fi
