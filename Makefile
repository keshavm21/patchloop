# Use the project venv when it exists, so targets work without activating it.
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: sandbox-image test chaos demo smoke clean-containers

sandbox-image:
	docker build -t patchloop-sandbox -f docker/sandbox.Dockerfile docker/

test:
	$(PYTHON) -m pytest tests/unit -q

chaos:
	$(PYTHON) -m pytest tests/sandbox -q

demo:
	$(PYTHON) -m patchloop solve benchmarks/examples/second_largest.json --config configs/full.yaml --llm replay

# The replay smoke eval: InjectBench at every defense level, with recorded model replies instead
# of a model. It must reproduce results/baseline_replay.json exactly and leak no canary.
smoke:
	$(PYTHON) -m patchloop.bench.injectbench
	$(PYTHON) -m patchloop eval --bench injectbench --split test --llm replay \
		--replay-file tests/replay/injectbench.jsonl --out runs/smoke \
		--config configs/defense_d0.yaml --config configs/defense_d1.yaml \
		--config configs/defense_d2.yaml --config configs/defense_d3.yaml \
		--assert-baseline results/baseline_replay.json

clean-containers:
	@ids="$$(docker ps -aq --filter label=patchloop)"; \
	if [ -n "$$ids" ]; then docker rm -f $$ids; else echo "no patchloop containers"; fi
	@vols="$$(docker volume ls -q --filter label=patchloop)"; \
	if [ -n "$$vols" ]; then docker volume rm $$vols; else echo "no patchloop volumes"; fi
