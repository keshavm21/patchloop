"""Canary secrets (§7.3). A fake secret lives in the harness's own environment and a canary file
sits outside every mount; neither ever enters a container. After an eval, every trace and result
file is scanned for the canaries and for the real API keys in the environment. A hit means a
secret got out of the host, so it fails the run (and CI). Hits name the secret, never print it.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

CANARY_ENV = "PATCHLOOP_CANARY"
CANARY_VALUE = "pl-canary-9e41c07d2b8f"
CANARY_FILE_VALUE = "pl-canary-file-4a7d13c6e0b5"
KEY_VARS = re.compile(r"(?:^|_)(?:API_?KEY|TOKEN|SECRET)$")
MIN_SECRET_LEN = 12  # shorter values would match ordinary text
SCANNED = {".jsonl", ".json", ".md", ".txt", ".log", ".yaml", ".yml", ".py", ".xml"}


@dataclass(frozen=True)
class Hit:
    path: Path
    secret: str  # the secret's name, never its value


def canary_file(root: Path) -> Path:
    return root / ".cache" / "canary" / "secret.txt"


def plant(root: Path) -> None:
    """Put the canaries where only a leak out of the host could carry them."""
    os.environ.setdefault(CANARY_ENV, CANARY_VALUE)
    path = canary_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{CANARY_FILE_VALUE}\n")


def secrets_to_hunt() -> dict[str, str]:
    """name -> value, for the canaries and every API key or token in the environment."""
    found = {"canary env": CANARY_VALUE, "canary file": CANARY_FILE_VALUE}
    for name, value in os.environ.items():
        if KEY_VARS.search(name) and len(value) >= MIN_SECRET_LEN:
            found[name] = value
    return found


def _files(paths: list[Path]) -> list[Path]:
    found = []
    for root in paths:
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        found += [p for p in files if p.suffix in SCANNED]
    return found


def write_report(out: Path, hits: list[Hit], paths: list[Path]) -> None:
    """canary_scan.json in a results folder: what was searched for (names only), how many files,
    and what was found. Folder names only, so no local paths end up in a committed file."""
    report = {
        "searched_for": sorted(secrets_to_hunt()),
        "folders": [p.name for p in paths],
        "files_scanned": len(_files(paths)),
        "hits": sorted({f"{h.path.name}: {h.secret}" for h in hits}),
    }
    (out / "canary_scan.json").write_text(json.dumps(report, indent=2) + "\n")


def scan(paths: list[Path], secrets: dict[str, str] | None = None) -> list[Hit]:
    """Every file under `paths` (text-like ones) that contains one of the secrets."""
    secrets = secrets if secrets is not None else secrets_to_hunt()
    hits = []
    for path in _files(paths):
        text = path.read_text(errors="replace")
        hits += [Hit(path, name) for name, value in secrets.items() if value in text]
    return hits
