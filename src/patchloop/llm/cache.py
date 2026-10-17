"""A disk cache of model replies, keyed by (model, messages, params, repeat index).

The repeat index is part of the key so that repeats stay independent: without it, repeat 2
would silently reuse repeat 1's answers.
"""

import hashlib
import json
import os
from pathlib import Path

from ..models import Usage
from .base import LLMClient, Message, Reply


class CachedClient:
    def __init__(self, inner: LLMClient, cache_dir: Path = Path(".cache/llm")) -> None:
        self.inner = inner
        self.model = inner.model
        self.cache_dir = Path(cache_dir)

    def chat(
        self, messages: list[Message], *, temperature: float, max_tokens: int, repeat: int = 0
    ) -> Reply:
        extra = getattr(self.inner, "params", {})
        key = cache_key(self.model, messages, temperature, max_tokens, repeat, extra)
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            entry = json.loads(path.read_text())
            # The recorded tokens and cost are kept, so those numbers don't depend on the cache;
            # the retries happened on the original call, not this one.
            usage = Usage.model_validate(entry["usage"]).model_copy(
                update={"cached_calls": 1, "retries": 0, "retry_wait_s": 0.0}
            )
            return Reply(entry["text"], usage, entry["model"], entry.get("finish_reason"))
        reply = self.inner.chat(
            messages, temperature=temperature, max_tokens=max_tokens, repeat=repeat
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "text": reply.text,
            "model": reply.model,
            "finish_reason": reply.finish_reason,
            "usage": reply.usage.model_dump(),
        }
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(entry))
        tmp.replace(path)  # atomic, so parallel workers never read half a file
        return reply


def cache_key(
    model: str,
    messages: list[Message],
    temperature: float,
    max_tokens: int,
    repeat: int,
    extra: dict | None = None,
) -> str:
    """Extra request parameters (such as reasoning_effort) join the key only when set, so
    entries cached without them keep their keys."""
    params = {"temperature": temperature, "max_tokens": max_tokens, **(extra or {})}
    payload = {"model": model, "messages": messages, "params": params, "repeat": repeat}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
