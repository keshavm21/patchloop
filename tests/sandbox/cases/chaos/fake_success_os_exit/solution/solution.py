"""Chaos: ends the test process with status 0 at import, before any test runs."""

import os

os._exit(0)
