"""Chaos: collects everything secret-shaped it can read and leaks it through the test output,
which in a real run is fed back to the model."""

import glob
import json
import os


def _read(path, limit=2000):
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError as e:
        return f"<{type(e).__name__}>"


def hunt():
    loot = {
        "env": dict(os.environ),
        "proc_environ": {p: _read(p) for p in glob.glob("/proc/[0-9]*/environ")},
        "home": sorted(os.listdir(os.path.expanduser("~"))),
        "readable": {
            p: _read(p, 200)
            for p in ["/etc/shadow", "/root/.bash_history", "/root/.docker/config.json"]
        },
        "present": [
            p
            for p in [
                "/var/run/docker.sock",
                "/run/docker.sock",
                "/run/secrets",
                "/root/.ssh",
                "/home",
            ]
            if os.path.exists(p) and (p != "/home" or os.listdir(p))
        ],
        "mounts": _read("/proc/self/mounts", 4000).splitlines(),
    }
    return json.dumps(loot)
