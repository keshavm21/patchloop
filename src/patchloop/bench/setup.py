"""Download a benchmark, convert it to tasks, validate them in the sandbox, split and freeze.

    python -m patchloop.bench.setup humanevalfix [--workers 3] [--revalidate]

The tasks are written to benchmarks/<name>/v1/tasks/, which is git-ignored: benchmarks are
downloaded, never re-hosted. Only benchmarks/<name>/v1/manifest.json is committed. It holds
the pinned dataset revision, every file's sha256, the dropped tasks with reasons, and the split.

The first run validates (§8.3) and writes the manifest. Later runs regenerate the files and
check them against the manifest, so the benchmark stays frozen: a mismatch is an error.
"""

import argparse
import hashlib
import importlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from ..sandbox.limits import Limits
from ..sandbox.sandbox import DockerSandbox
from .split import DEV_FRACTION, SEED, stratified_split
from .validate import check_all

ROOT = Path(__file__).resolve().parents[3]
BENCHMARKS = ROOT / "benchmarks"
VERSION = "v1"


# name -> the meta key the split is stratified by. Each module provides DATASET, REVISION,
# PER_TEST_TIMEOUT_S, Unusable, load_rows(), row_slug(row) and build(row) (one spec or a list),
# and optionally select(valid_specs) to sample from the validated ones.
BENCHES = {"humanevalfix": "bug_type", "mutbench": "operator"}


def bench_module(name: str):
    return importlib.import_module(f"patchloop.bench.{name}")


def build_specs(module) -> tuple[list, dict[str, str]]:
    specs, dropped = [], {}
    for row in module.load_rows():
        try:
            built = module.build(row)
        except module.Unusable as e:
            dropped[module.row_slug(row)] = f"conversion: {e}"
            continue
        specs.extend(built if isinstance(built, list) else [built])
    return specs, dropped


def file_hashes(tasks_dir: Path, slug: str) -> dict[str, str]:
    paths = [tasks_dir / f"{slug}.json", *sorted((tasks_dir / slug).rglob("*"))]
    return {
        str(p.relative_to(tasks_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
        if p.is_file()
    }


def checksum(tasks: dict) -> str:
    """One hash over every kept task's files: the dataset checksum recorded with results."""
    files = {slug: t["files"] for slug, t in sorted(tasks.items())}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def remove_task(tasks_dir: Path, slug: str) -> None:
    (tasks_dir / f"{slug}.json").unlink(missing_ok=True)
    shutil.rmtree(tasks_dir / slug, ignore_errors=True)


def setup(name: str, *, workers: int, revalidate: bool) -> int:
    module, stratum_key = bench_module(name), BENCHES[name]
    out = BENCHMARKS / name / VERSION
    tasks_dir, manifest_path = out / "tasks", out / "manifest.json"
    shutil.rmtree(tasks_dir, ignore_errors=True)
    tasks_dir.mkdir(parents=True)

    print(f"building {name} from {module.DATASET}@{module.REVISION[:12]}", flush=True)
    specs, dropped = build_specs(module)
    for spec in specs:
        spec.write(tasks_dir)
    print(f"{len(specs)} tasks built, {len(dropped)} dropped during conversion", flush=True)

    if manifest_path.exists() and not revalidate:
        return verify(json.loads(manifest_path.read_text()), tasks_dir, specs)

    def progress(slug: str, reason: str | None) -> None:
        print(
            f"  {'ok  ' if reason is None else 'DROP'} {slug}" + (f": {reason}" if reason else "")
        )

    limits = Limits(per_test_timeout_s=module.PER_TEST_TIMEOUT_S)
    work = ROOT / "runs" / "validate" / name
    shutil.rmtree(work, ignore_errors=True)
    results = check_all(
        [tasks_dir / f"{s.slug}.json" for s in specs],
        lambda path: DockerSandbox(work / path.stem, limits),
        workers=workers,
        progress=progress,
    )
    shutil.rmtree(work, ignore_errors=True)
    valid = [s for s in specs if results[s.slug].reason is None]
    dropped |= {slug: f"validation: {o.reason}" for slug, o in results.items() if o.reason}
    if hasattr(module, "label"):  # labels that come from the validation runs (symptoms)
        for spec in valid:
            module.label(spec, results[spec.slug].buggy_status)
            spec.write(tasks_dir)
    kept = module.select(valid) if hasattr(module, "select") else valid
    kept_slugs = {s.slug for s in kept}
    for spec in specs:
        if spec.slug not in kept_slugs:
            remove_task(tasks_dir, spec.slug)

    split = stratified_split({s.slug: str(s.meta[stratum_key]) for s in kept})
    tasks = {
        s.slug: {
            "id": s.id,
            "split": split[s.slug],
            "stratum": s.meta[stratum_key],
            "expected_counts": {"visible": s.visible_count, "hidden": s.hidden_count},
            "labels": {k: s.meta[k] for k in getattr(module, "LABEL_KEYS", ())},
            "files": file_hashes(tasks_dir, s.slug),
        }
        for s in sorted(kept, key=lambda s: s.slug)
    }
    manifest = {
        "name": name,
        "version": VERSION,
        "dataset": {"repo": module.DATASET, "revision": module.REVISION},
        "built": {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_sha": _git("rev-parse", "HEAD"),
            "image_id": _image_id(limits.image),
            "arch": platform.machine(),
        },
        "split": {
            "seed": SEED,
            "dev_fraction": DEV_FRACTION,
            "stratified_by": stratum_key,
            "counts": {
                part: sum(t["split"] == part for t in tasks.values()) for part in ("dev", "test")
            },
        },
        "checksum": checksum(tasks),
        "valid_not_selected": len(valid) - len(kept),
        "tasks": tasks,
        "dropped": dict(sorted(dropped.items())),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    counts = manifest["split"]["counts"]
    print(
        f"froze {len(tasks)} tasks (dev {counts['dev']}, test {counts['test']}), "
        f"dropped {len(dropped)} -> {manifest_path}"
    )
    return 0


def verify(manifest: dict, tasks_dir: Path, specs: list) -> int:
    """Regenerated files must match the frozen manifest exactly."""
    for spec in specs:
        if spec.slug not in manifest["tasks"]:
            remove_task(tasks_dir, spec.slug)
        elif labels := manifest["tasks"][spec.slug].get("labels"):
            spec.meta.update(labels)
            spec.write(tasks_dir)
    problems = []
    for slug, task in manifest["tasks"].items():
        if not (tasks_dir / f"{slug}.json").exists():
            problems.append(f"{slug}: missing after regeneration")
        elif file_hashes(tasks_dir, slug) != task["files"]:
            problems.append(f"{slug}: files differ from the manifest")
    if problems:
        print("the regenerated benchmark does not match the frozen manifest:", file=sys.stderr)
        print("\n".join(f"  {p}" for p in problems[:20]), file=sys.stderr)
        return 1
    print(f"verified {len(manifest['tasks'])} tasks against the manifest (checksum ok)")
    return 0


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT).stdout.strip()


def _image_id(image: str) -> str:
    import docker

    return docker.from_env().images.get(image).id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("name", choices=sorted(BENCHES))
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--revalidate", action="store_true", help="rebuild the manifest")
    args = parser.parse_args()
    raise SystemExit(setup(args.name, workers=args.workers, revalidate=args.revalidate))


if __name__ == "__main__":
    main()
