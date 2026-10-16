"""Shared fixtures for the unit tests."""

from pathlib import Path

import pytest

from patchloop.models import Task

EXAMPLES = Path(__file__).resolve().parents[2] / "benchmarks" / "examples"


@pytest.fixture
def task() -> Task:
    """A real example task; its files are read from disk, but nothing runs."""
    return Task.load(EXAMPLES / "second_largest.json")
