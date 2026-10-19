"""Load a frozen benchmark: the tasks listed in its manifest, checked against their hashes."""

import json
from dataclasses import dataclass

from ..models import Task
from .setup import BENCHMARKS, VERSION, file_hashes


class BenchmarkMissing(RuntimeError):
    pass


@dataclass(frozen=True)
class Benchmark:
    name: str
    manifest: dict
    tasks: list[Task]

    @property
    def checksum(self) -> str:
        return self.manifest["checksum"]


def load_benchmark(name: str, split: str = "all", *, version: str = VERSION) -> Benchmark:
    """The benchmark's tasks in `split` ("dev", "test" or "all"), in a stable order.

    Raises BenchmarkMissing if the files haven't been generated, or no longer match the
    manifest; `python -m patchloop.bench.setup <name>` regenerates and verifies them.
    """
    root = BENCHMARKS / name / version
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise BenchmarkMissing(f"no manifest at {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    tasks_dir = root / "tasks"
    tasks = []
    for slug, entry in sorted(manifest["tasks"].items()):
        if split != "all" and entry["split"] != split:
            continue
        if (
            not (tasks_dir / f"{slug}.json").exists()
            or file_hashes(tasks_dir, slug) != entry["files"]
        ):
            raise BenchmarkMissing(
                f"{name} task {slug} is missing or differs from the manifest; "
                f"run `python -m patchloop.bench.setup {name}`"
            )
        tasks.append(Task.load(tasks_dir / f"{slug}.json"))
    return Benchmark(name, manifest, tasks)
