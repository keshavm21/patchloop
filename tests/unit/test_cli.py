from typer.testing import CliRunner

from patchloop import __version__
from patchloop.cli import app


def test_version_flag_prints_version():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout == f"patchloop {__version__}\n"
