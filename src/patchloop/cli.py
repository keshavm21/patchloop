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
) -> None:
    """Repair one task: attempts against the visible tests, then the hidden verdict."""
    from .agent.loop import solve as solve_task
    from .config import AgentConfig, load_config
    from .llm.cache import CachedClient
    from .llm.openai_compat import OpenAICompatClient
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
    model_cfg = cfg.model
    if not model_cfg.name:
        raise typer.BadParameter("no model set: pass --model, or set model.name in the config")

    api_key = _secret(model_cfg.api_key_env)
    if not api_key and not _is_local(model_cfg.base_url):
        raise typer.BadParameter(
            f"{model_cfg.api_key_env} is not set; put it in .env (see .env.example)"
        )
    llm = OpenAICompatClient(
        model_cfg.name, api_key=api_key, base_url=model_cfg.base_url, price=model_cfg.price
    )
    if cache:
        llm = CachedClient(llm)

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
