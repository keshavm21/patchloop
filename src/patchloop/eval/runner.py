"""Run configs × tasks × repeats and append one line per finished run to records.jsonl.

Resuming skips (task, config, repeat) triples that already have a record. Infra errors
(model API or Docker failures after their own retries) are retried on later passes and,
after `infra_retries` of them, quarantined: recorded, reported separately, and never counted
as agent failures. A run of consecutive infra errors stops the eval early: on a free tier it
usually means the quota is spent, and resuming later picks up where it left off.
"""

import json
import platform
import subprocess
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..agent.loop import solve
from ..bench.frozen import Benchmark
from ..config import AgentConfig
from ..llm.base import LLMClient, QuotaExhausted
from ..models import StopReason, Task
from ..sandbox.docker_runner import SandboxUnavailable
from ..sandbox.limits import Limits
from ..sandbox.sandbox import DockerSandbox, Sandbox
from ..tracing import Tracer

ROOT = Path(__file__).resolve().parents[3]
RECORDS = "records.jsonl"


@dataclass
class EvalPlan:
    bench: Benchmark
    split: str
    configs: list[AgentConfig]
    repeats: int
    out: Path  # results folder: records.jsonl lives here
    work: Path  # run folders and traces (git-ignored), inside the project for Colima
    workers: int = 1
    infra_retries: int = 2
    stop_after_infra_errors: int = 5
    max_cost_usd: float | None = None


@dataclass
class EvalSummary:
    ran: int = 0
    skipped: int = 0
    infra_errors: int = 0
    stopped_early: str | None = None
    quota_exhausted: bool = False  # or Docker down: wait and resume, nothing was recorded


def read_records(out: Path) -> list[dict]:
    path = out / RECORDS
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def pending(plan: EvalPlan, records: list[dict]) -> list[tuple[Task, AgentConfig, int]]:
    """Triples without a finished record, and infra failures that still have retries left."""
    done, infra = set(), {}
    for r in records:
        key = (r["task_id"], r["config"], r["repeat"])
        if r["stop_reason"] == StopReason.INFRA_ERROR:
            infra[key] = infra.get(key, 0) + 1
        else:
            done.add(key)
    todo = []
    for cfg in plan.configs:
        for repeat in range(plan.repeats):
            for task in plan.bench.tasks:
                key = (task.id, cfg.name, repeat)
                if key not in done and infra.get(key, 0) <= plan.infra_retries:
                    todo.append((task, cfg, repeat))
    return todo


class SettingsMismatch(ValueError):
    """The results folder already has runs under a config name, made with other settings."""


def check_settings(plan: EvalPlan, records: list[dict]) -> None:
    """Resuming must never mix settings under one config name: completed runs would be
    skipped although they were made differently."""
    current = {cfg.name: cfg.model_dump(mode="json") for cfg in plan.configs}
    for r in records:
        before = r["provenance"]["config"]
        if r["config"] in current and before != current[r["config"]]:
            changed = sorted(
                k
                for k in set(before) | set(current[r["config"]])
                if before.get(k) != current[r["config"]].get(k)
            )
            raise SettingsMismatch(
                f"{plan.out} has runs of config {r['config']!r} made with different settings "
                f"({', '.join(changed)}); use another --out"
            )


def run_eval(
    plan: EvalPlan,
    llm_for: Callable[[AgentConfig], LLMClient],
    *,
    sandbox_for: Callable[[Path], Sandbox] | None = None,
    on_record: Callable[[dict], None] = lambda record: None,
) -> EvalSummary:
    plan.out.mkdir(parents=True, exist_ok=True)
    records = read_records(plan.out)
    check_settings(plan, records)
    todo = pending(plan, records)
    summary = EvalSummary(skipped=_count_triples(plan) - len(todo))
    if not todo:
        return summary
    sandbox_for = sandbox_for or (lambda work: DockerSandbox(work, Limits()))
    provenance = {cfg.name: _provenance(plan, cfg) for cfg in plan.configs}
    clients = {cfg.name: llm_for(cfg) for cfg in plan.configs}
    lock = threading.Lock()
    state = {"streak": 0, "cost": sum(r["usage"].get("cost_usd") or 0.0 for r in records)}
    stop = threading.Event()

    def one(task: Task, cfg: AgentConfig, repeat: int) -> None:
        if stop.is_set():
            return
        slug = task.id.replace("/", "_")
        work = plan.work / slug / cfg.name / f"r{repeat}"
        tracer = Tracer(work / "trace.jsonl", run=f"{task.id}/{cfg.name}/r{repeat}")
        try:
            rec = solve(
                task, cfg, clients[cfg.name], sandbox_for(work), tracer=tracer, repeat=repeat
            )
        except (QuotaExhausted, SandboxUnavailable) as e:
            with lock:  # no record: the triple stays pending, and resuming reruns it
                what = "daily quota spent" if isinstance(e, QuotaExhausted) else "Docker is down"
                summary.stopped_early = f"{what} ({e}); resume later"
                summary.quota_exhausted = True
            stop.set()
            return
        record = {
            **json.loads(rec.model_dump_json()),
            "bench": plan.bench.name,
            "split": plan.split,
            "meta": {k: v for k, v in task.meta.items() if k != "reference"},
            "expected_counts": task.expected_counts.model_dump(),
            "max_attempts": cfg.max_attempts,
            "trace": str(work.relative_to(ROOT) / "trace.jsonl")
            if work.is_relative_to(ROOT)
            else "",
            "provenance": provenance[cfg.name],
        }
        with lock:
            with (plan.out / RECORDS).open("a") as f:
                f.write(json.dumps(record) + "\n")
            summary.ran += 1
            if rec.stop_reason is StopReason.INFRA_ERROR:
                summary.infra_errors += 1
                state["streak"] += 1
                if state["streak"] >= plan.stop_after_infra_errors:
                    summary.stopped_early = (
                        f"{state['streak']} infra errors in a row (last: {rec.infra_error}); "
                        "the provider may be down or the quota spent. Resume later."
                    )
                    stop.set()
            else:
                state["streak"] = 0
            state["cost"] += (rec.usage.cost_usd or 0.0) + (rec.explanation_usage.cost_usd or 0.0)
            if plan.max_cost_usd is not None and state["cost"] >= plan.max_cost_usd:
                summary.stopped_early = f"cost cap reached (${state['cost']:.4f})"
                stop.set()
        on_record(record)

    # The first pass runs everything; later passes retry the infra errors, until each triple
    # has either finished or used up its retries.
    for _ in range(plan.infra_retries + 1):
        with ThreadPoolExecutor(max_workers=plan.workers) as pool:
            for future in as_completed([pool.submit(one, *triple) for triple in todo]):
                future.result()
        todo = pending(plan, read_records(plan.out))
        if not todo or stop.is_set():
            break
    return summary


def _count_triples(plan: EvalPlan) -> int:
    return len(plan.configs) * plan.repeats * len(plan.bench.tasks)


def _provenance(plan: EvalPlan, cfg: AgentConfig) -> dict:
    """What every result must be traceable to (§8.6)."""
    import docker

    image = Limits().image
    try:
        image_id = docker.from_env().images.get(image).id
    except Exception:  # a fake sandbox in tests; the real runs fail loudly later
        image_id = None
    return {
        "model": cfg.model.name,
        "base_url": cfg.model.base_url,
        "temperature": cfg.model.temperature,
        "prompt_version": cfg.prompt_version,
        "config": cfg.model_dump(mode="json"),
        "git_sha": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--", "src", "docker", "prompts")),
        "image_id": image_id,
        "dataset": plan.bench.name,
        "dataset_checksum": plan.bench.checksum,
        "arch": platform.machine(),
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT).stdout.strip()
