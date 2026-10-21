import pytest

from patchloop.safety.policy import check


def blocked(code: str) -> list[str]:
    return check(code).blocked


@pytest.mark.parametrize(
    "code, reason",
    [
        ("import socket\n", "network"),
        ("from urllib.request import urlopen\n", "network"),
        ("import subprocess\n", "process control"),
        ("import os\nos.system('id')\n", "process control"),
        ("import os as o\no.fork()\n", "process control"),
        ("from os import system\n", "process control"),
        ("import os\nos.execv('/bin/sh', [])\n", "process control"),
        ("eval('1')\n", "dynamic code"),
        ("exec('x = 1')\n", "dynamic code"),
        ("compile('1', 'f', 'eval')\n", "dynamic code"),
        ("__import__('os')\n", "dynamic code"),
        ("import ctypes\n", "native access"),
        ("open('f', 'w')\n", "file writes"),
        ("open('f', mode='a+')\n", "file writes"),
        ("import shutil\n", "file writes"),
        ("import os\nos.remove('f')\n", "file writes"),
        ("from pathlib import Path\nPath('f').write_text('x')\n", "file writes"),
        ("import os\nx = os.environ['KEY']\n", "secrets"),
        ("import os\nos.getenv('KEY')\n", "secrets"),
        ("from os import environ\n", "secrets"),
        ("import sys\nsys.exit(0)\n", "result tampering"),
        ("import os\nos._exit(0)\n", "result tampering"),
        ("import atexit\n", "result tampering"),
        ("import pytest\n", "result tampering"),
        ("import unittest\n", "result tampering"),
    ],
)
def test_blocks(code, reason):
    findings = blocked(code)
    assert findings and reason in findings[0]


def test_message_names_the_line_and_the_fix():
    out = blocked("x = 1\n\nimport subprocess\n")
    assert out == ["line 3 imports `subprocess`, which is not allowed (process control)"]


@pytest.mark.parametrize(
    "code",
    [
        "import os\nos.path.join('a', 'b')\n",
        "import os.path\nos.path.exists('x')\n",
        "from os import path, sep\n",
        "import re, math, itertools, functools, collections, heapq, bisect\n",
        "from typing import List\n",
        "open('f')\nopen('f', 'r')\nopen('f', 'rb')\n",
        "import json\njson.dumps({})\n",
        "environ = {}\nenviron['k'] = 1\n",
        "def f(exit_code):\n    return exit_code\n",
    ],
)
def test_allows_ordinary_code(code):
    result = check(code)
    assert not result.blocked and not result.flagged


def test_import_aliases_are_resolved():
    assert blocked("import os as operating\noperating.system('x')\n")
    assert blocked("from os import environ as e\ne['k']\n")


def test_introspection_is_flagged_not_blocked():
    result = check("x = ().__class__.__bases__[0].__subclasses__()\ny = globals()\n")
    assert not result.blocked
    assert len(result.flagged) == 2


def test_non_literal_open_mode_is_flagged():
    result = check("m = 'w'\nopen('f', m)\n")
    assert not result.blocked and result.flagged


def test_code_that_does_not_parse_has_no_findings():
    result = check("def broken(:\n")
    assert not result.blocked and not result.flagged


def test_rules_file_matches_what_the_code_reads():
    from patchloop.safety.policy import load_rules

    rules = load_rules()
    assert set(rules) == {"block", "flag"}
    assert "os.system" in rules["block"]["names"]["process control"]
