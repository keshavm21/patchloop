"""A scripted model for tests: returns its replies in order and records every prompt."""

from ..models import Usage
from .base import LLMInfraError, Message, Reply


class FakeLLM:
    def __init__(
        self, replies: list[str | Exception], *, model: str = "fake", tokens: int = 100
    ) -> None:
        self.model = model
        self.replies = list(replies)
        self.tokens = tokens  # input and output tokens charged per call
        self.calls: list[list[Message]] = []

    def chat(
        self, messages: list[Message], *, temperature: float, max_tokens: int, repeat: int = 0
    ) -> Reply:
        self.calls.append(messages)
        if not self.replies:
            raise LLMInfraError("FakeLLM ran out of scripted replies")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        usage = Usage(input_tokens=self.tokens, output_tokens=self.tokens, calls=1)
        return Reply(text=reply, usage=usage, model=self.model)
