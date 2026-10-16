"""The interface the loop talks to. Every client returns a Reply with its usage, so token,
cost and latency accounting works the same for hosted APIs, Ollama, the cache and the fakes."""

from dataclasses import dataclass
from typing import Protocol

from ..config import Price
from ..models import Usage

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": ...}


class LLMInfraError(RuntimeError):
    """The model API failed after retries (429, 5xx, connection, or a bad request). An infra
    error, never the agent's fault."""


@dataclass(frozen=True)
class Reply:
    text: str
    usage: Usage
    model: str


class LLMClient(Protocol):
    model: str

    def chat(
        self, messages: list[Message], *, temperature: float, max_tokens: int, repeat: int = 0
    ) -> Reply:
        """One chat completion. `repeat` keeps repeats of the same run apart in the cache."""
        ...


def cost_usd(price: Price | None, input_tokens: int, output_tokens: int) -> float | None:
    if price is None:
        return None
    return (input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok) / 1e6
