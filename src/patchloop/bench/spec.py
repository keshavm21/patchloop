"""A benchmark task before it's frozen: everything needed to write its task JSON and folders."""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TaskSpec:
    slug: str  # folder and file name
    id: str
    instruction: str
    starting_code: str
    reference: str
    visible_tests: dict[str, str]  # file name -> source
    hidden_tests: dict[str, str]
    visible_count: int
    hidden_count: int
    meta: dict = field(default_factory=dict)
    support: dict[str, str] = field(default_factory=dict)  # hidden-side data files

    def write(self, root: Path) -> Path:
        """Write <root>/<slug>.json plus <root>/<slug>/{reference.py, tests/...}; returns the
        JSON path. The reference sits outside the JSON, and nothing in a prompt reads meta."""
        folder = root / self.slug
        files = {
            "reference.py": self.reference,
            **{f"tests/visible/{n}": s for n, s in self.visible_tests.items()},
            **{f"tests/hidden/{n}": s for n, s in {**self.hidden_tests, **self.support}.items()},
        }
        for rel, text in files.items():
            path = folder / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        task = {
            "id": self.id,
            "mode": "repair",
            "instruction": self.instruction,
            "entrypoint": "solution.py",
            "files": {"solution.py": self.starting_code},
            "visible_tests": f"{self.slug}/tests/visible/",
            "hidden_tests": f"{self.slug}/tests/hidden/",
            "expected_counts": {"visible": self.visible_count, "hidden": self.hidden_count},
            "meta": {**self.meta, "reference": f"{self.slug}/reference.py"},
        }
        path = root / f"{self.slug}.json"
        path.write_text(json.dumps(task, indent=2, sort_keys=True) + "\n")
        return path
