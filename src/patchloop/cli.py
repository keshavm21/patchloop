"""The `patchloop` command line."""

from typing import Annotated

import typer

from . import __version__

app = typer.Typer(no_args_is_help=True, add_completion=False)


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
