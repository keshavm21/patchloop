"""Recorded model replies, so `make demo` and CI can run the real loop with no API key.

A fixture file is JSON lines, one per call: the prompt's hash, the model, and the reply with
its usage. Replay looks a reply up by the exact prompt, so any change to a prompt template or
to the code under repair makes the lookup fail loudly instead of replaying a stale answer;
re-record with `patchloop solve ... --record <file>`.
"""

import hashlib
import json
from pathlib import Path

from ..models import Usage
from .base import LLMClient, LLMInfraError, Message, Reply


def prompt_key(messages: list[Message], repeat: int) -> str:
    payload = json.dumps({"messages": messages, "repeat": repeat}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class ReplayLLM:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"no replay fixtures at {self.path}")
        entries = [json.loads(line) for line in self.path.read_text().splitlines() if line]
        self.replies = {e["key"]: e for e in entries}
        self.model = entries[0]["model"] if entries else "replay"

    def chat(
        self, messages: list[Message], *, temperature: float, max_tokens: int, repeat: int = 0
    ) -> Reply:
        entry = self.replies.get(prompt_key(messages, repeat))
        if entry is None:
            raise LLMInfraError(
                f"no recorded reply for this prompt in {self.path}; prompts or code changed "
                "since recording, so re-record with `patchloop solve ... --record`"
            )
        usage = Usage.model_validate(entry["usage"]).model_copy(
            update={"cached_calls": 1, "retries": 0, "retry_wait_s": 0.0}
        )
        return Reply(entry["text"], usage, entry["model"], entry.get("finish_reason"))


class RecordingLLM:
    """Wraps a real client and appends every reply to a fixture file."""

    def __init__(self, inner: LLMClient, path: Path) -> None:
        self.inner = inner
        self.model = inner.model
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def chat(
        self, messages: list[Message], *, temperature: float, max_tokens: int, repeat: int = 0
    ) -> Reply:
        reply = self.inner.chat(
            messages, temperature=temperature, max_tokens=max_tokens, repeat=repeat
        )
        entry = {
            "key": prompt_key(messages, repeat),
            "model": reply.model,
            "text": reply.text,
            "finish_reason": reply.finish_reason,
            "usage": reply.usage.model_dump(),
        }
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        return reply
