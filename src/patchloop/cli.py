"""The `patchloop` command line."""

import os
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from . import __version__

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"patchloop {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", help="Show the version and exit.", callback=_show_version, is_eager=True
        ),
    ] = False,
) -> None:
    """A sandboxed, self-repairing coding agent."""


@app.command()
def solve(
    task_path: Annotated[Path, typer.Argument(help="A task JSON file.", exists=True)],
    config: Annotated[Path | None, typer.Option(help="A configs/*.yaml file.")] = None,
    model: Annotated[str | None, typer.Option(help="Model name; overrides the config.")] = None,
    base_url: Annotated[
        str | None, typer.Option(help="OpenAI-compatible endpoint, e.g. Ollama's.")
    ] = None,
    max_attempts: Annotated[int | None, typer.Option(min=1)] = None,
    feedback: Annotated[str | None, typer.Option(help="L0, L1, L2 or L3.")] = None,
    reflect: Annotated[bool | None, typer.Option("--reflect/--no-reflect")] = None,
    repeat: Annotated[int, typer.Option(min=0, help="Repeat index (part of the cache key).")] = 0,
    cache: Annotated[bool, typer.Option("--cache/--no-cache")] = True,
    out: Annotated[Path, typer.Option(help="Where run folders go; keep it inside the project.")] = (
        Path("runs")
    ),
    llm_kind: Annotated[
        str, typer.Option("--llm", help="api (the configured model) or replay (recorded replies).")
    ] = "api",
    replay_file: Annotated[Path, typer.Option(help="Fixtures for --llm replay.")] = Path(
        "tests/replay/demo.jsonl"
    ),
    record: Annotated[
        Path | None, typer.Option(help="Append every real reply to this fixture file.")
    ] = None,
) -> None:
    """Repair one task: attempts against the visible tests, then the hidden verdict."""
    from .agent.loop import solve as solve_task
    from .config import AgentConfig, load_config
    from .models import StopReason, Task
    from .sandbox.sandbox import DockerSandbox
    from .tracing import Tracer
    from .view import LiveView

    cfg = load_config(config) if config else AgentConfig(name="default")
    data = cfg.model_dump()
    for key, value in {
        "max_attempts": max_attempts,
        "feedback": feedback,
        "reflect": reflect,
    }.items():
        if value is not None:
            data[key] = value
    for key, value in {"name": model, "base_url": base_url}.items():
        if value is not None:
            data["model"][key] = value
    cfg = AgentConfig.model_validate(data)  # validates the overrides too (e.g. --feedback L9)
    if llm_kind == "replay":
        from .llm.replay import ReplayLLM

        try:
            llm = ReplayLLM(replay_file)
        except FileNotFoundError as e:
            raise typer.BadParameter(str(e)) from None
    elif llm_kind == "api":
        if not cfg.model.name:
            raise typer.BadParameter("no model set: pass --model, or set model.name in the config")
        llm = _make_llm(cfg.model, cache=cache and record is None)
        if record:
            from .llm.replay import RecordingLLM

            llm = RecordingLLM(llm, record)
    else:
        raise typer.BadParameter("--llm must be api or replay")

    task = Task.load(task_path)
    now = datetime.now()
    run_dir = out / f"{now:%Y-%m-%d}" / task.id.replace("/", "_")
    run_dir = run_dir / f"{now:%H%M%S}-{cfg.name}-r{repeat}"
    tracer = Tracer(
        run_dir / "trace.jsonl",
        run=f"{task.id}/{cfg.name}/r{repeat}",
        listeners=[LiveView(console)],
    )
    rec = solve_task(task, cfg, llm, DockerSandbox(run_dir), tracer=tracer, repeat=repeat)
    (run_dir / "record.json").write_text(rec.model_dump_json(indent=2) + "\n")
    console.print(f"{'trace':<10} {run_dir / 'trace.jsonl'}", highlight=False)
    if rec.stop_reason is StopReason.INFRA_ERROR:
        raise typer.Exit(2)
    raise typer.Exit(0 if rec.solved else 1)


@app.command()
def replay(
    trace: Annotated[Path, typer.Argument(help="A trace.jsonl, or the run folder holding it.")],
) -> None:
    """Show a recorded run as a timeline, with the code diff of each attempt."""
    from .tracing import read_trace
    from .view import render_replay

    path = trace / "trace.jsonl" if trace.is_dir() else trace
    if not path.exists():
        raise typer.BadParameter(f"{path} does not exist")
    render_replay(read_trace(path), console)


@app.command("eval")
def eval_(
    bench: Annotated[str, typer.Option(help="A frozen benchmark: humanevalfix or mutbench.")],
    config: Annotated[list[Path], typer.Option(help="configs/*.yaml; repeat to compare.")],
    split: Annotated[str, typer.Option(help="dev, test or all.")] = "dev",
    repeats: Annotated[int, typer.Option(min=1)] = 1,
    workers: Annotated[
        int, typer.Option(min=1, help="Parallel runs; keep low on a free tier.")
    ] = 1,
    limit: Annotated[int | None, typer.Option(min=1, help="Only the first N tasks.")] = None,
    out: Annotated[Path | None, typer.Option(help="Results folder.")] = None,
    max_cost_usd: Annotated[
        float | None, typer.Option(help="Stop once this much is spent.")
    ] = None,
    cache: Annotated[bool, typer.Option("--cache/--no-cache")] = True,
) -> None:
    """Run configs × tasks × repeats on a frozen benchmark; resumable."""
    from .bench.frozen import BenchmarkMissing, load_benchmark
    from .config import load_config
    from .eval.runner import ROOT, EvalPlan, SettingsMismatch, run_eval

    if split not in ("dev", "test", "all"):
        raise typer.BadParameter("--split must be dev, test or all")
    try:
        benchmark = load_benchmark(bench, split)
    except BenchmarkMissing as e:
        raise typer.BadParameter(str(e)) from None
    if limit:
        benchmark = type(benchmark)(benchmark.name, benchmark.manifest, benchmark.tasks[:limit])
    configs = [load_config(path) for path in config]
    for cfg in configs:
        if not cfg.model.name:
            raise typer.BadParameter(f"{cfg.name}: no model.name in the config")
    out = out or ROOT / "results" / f"{bench}-{split}"
    plan = EvalPlan(
        bench=benchmark,
        split=split,
        configs=configs,
        repeats=repeats,
        out=out,
        work=ROOT / "runs" / "eval" / out.name,
        workers=workers,
        max_cost_usd=max_cost_usd,
    )
    runs = len(benchmark.tasks) * len(configs) * repeats
    calls = len(benchmark.tasks) * repeats * sum(c.max_attempts for c in configs)
    console.print(
        f"{bench}/{split}: {len(benchmark.tasks)} tasks × {len(configs)} configs × {repeats} "
        f"repeats = {runs} runs, at most {calls} model calls (cached ones are free) -> {out}",
        highlight=False,
    )

    def show(record: dict) -> None:
        hidden = record.get("hidden_result") or {}
        verdict = "solved" if hidden.get("status") == "PASSED" else record["stop_reason"]
        console.print(
            f"  {record['config']:<14} r{record['repeat']}  {record['task_id']:<28} "
            f"{verdict:<16} attempts {len(record['attempts'])}",
            highlight=False,
        )

    try:
        summary = run_eval(plan, lambda cfg: _make_llm(cfg.model, cache=cache), on_record=show)
    except SettingsMismatch as e:
        raise typer.BadParameter(str(e)) from None
    latest = ROOT / "results" / "latest"
    if latest.is_symlink() or not latest.exists():
        latest.unlink(missing_ok=True)
        latest.symlink_to(out.name)
    console.print(
        f"ran {summary.ran}, skipped {summary.skipped} already done, "
        f"{summary.infra_errors} infra errors",
        highlight=False,
    )
    if summary.stopped_early:
        console.print(f"stopped early: {summary.stopped_early}", style="yellow", highlight=False)
        raise typer.Exit(3 if summary.quota_exhausted else 2)


@app.command()
def report(
    results: Annotated[Path, typer.Argument(help="A results folder holding records.jsonl.")],
) -> None:
    """Write report.md and success_at_k.png for a results folder."""
    from .eval.report import write_report

    try:
        path = write_report(results.resolve())
    except FileNotFoundError as e:
        raise typer.BadParameter(str(e)) from None
    console.print(path.read_text(), highlight=False, markup=False)
    console.print(f"wrote {path}", highlight=False)


def _make_llm(model_cfg, *, cache: bool):
    from .llm.cache import CachedClient
    from .llm.openai_compat import OpenAICompatClient

    api_key = _secret(model_cfg.api_key_env)
    if not api_key and not _is_local(model_cfg.base_url):
        raise typer.BadParameter(
            f"{model_cfg.api_key_env} is not set; put it in .env (see .env.example)"
        )
    llm = OpenAICompatClient(
        model_cfg.name,
        api_key=api_key,
        base_url=model_cfg.base_url,
        price=model_cfg.price,
        reasoning_effort=model_cfg.reasoning_effort,
    )
    return CachedClient(llm) if cache else llm


def _secret(name: str) -> str | None:
    """From the environment, else from ./.env. Only the harness reads it; it never enters a
    container."""
    if value := os.environ.get(name):
        return value
    env = Path(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name and value.strip():
                return value.strip().strip("\"'")
    return None


def _is_local(base_url: str | None) -> bool:
    return bool(base_url) and any(h in base_url for h in ("localhost", "127.0.0.1"))
