"""Every step of a run as one JSON line in trace.jsonl: llm_call, parse, policy_check,
sandbox_run, feedback, hidden_verdict and stop. Listeners (the CLI's live view) see each
event as it's written."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

Listener = Callable[[dict], None]


class Tracer:
    def __init__(
        self, path: Path | None = None, *, run: str = "", listeners: list[Listener] | None = None
    ) -> None:
        self.path = Path(path) if path else None
        self.run = run
        self.listeners = list(listeners or [])
        self.events: list[dict] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("")

    def emit(self, event: str, attempt: int | None = None, **fields) -> None:
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "run": self.run,
            "attempt": attempt,
            "event": event,
            **fields,
        }
        self.events.append(record)
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(record, default=str) + "\n")
        for listener in self.listeners:
            listener(record)


def read_trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
