"""Any OpenAI-compatible chat endpoint: hosted APIs, or Ollama at http://localhost:11434/v1."""

import random
import time
from collections.abc import Callable

import openai

from ..config import Price
from ..models import Usage
from .base import LLMInfraError, Message, QuotaExhausted, Reply, cost_usd

# Worth retrying: rate limits, server errors, timeouts and dropped connections.
_RETRYABLE = (
    openai.RateLimitError,
    openai.InternalServerError,
    openai.APITimeoutError,
    openai.APIConnectionError,
)


class OpenAICompatClient:
    def __init__(
        self,
        model: str,
        *,
        api_key: str | None,
        base_url: str | None = None,
        price: Price | None = None,
        reasoning_effort: str | None = None,
        max_retries: int = 5,
        timeout_s: float = 120.0,
        client=None,  # an openai.OpenAI, or a stand-in in tests
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.price = price
        # Extra request parameters; they are part of the cache key (see CachedClient).
        self.params = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
        self.max_retries = max_retries
        self._sleep = sleep
        # The SDK's own retries are off, so every retry goes through the backoff below.
        self._client = client or openai.OpenAI(
            api_key=api_key or "unused",  # Ollama ignores the key, but the SDK requires one
            base_url=base_url,
            timeout=timeout_s,
            max_retries=0,
        )

    def chat(
        self, messages: list[Message], *, temperature: float, max_tokens: int, repeat: int = 0
    ) -> Reply:
        first_try = time.monotonic()
        for attempt in range(self.max_retries + 1):
            start = time.monotonic()
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **self.params,
                )
            except _RETRYABLE as e:
                if _is_daily_quota(e):  # waiting seconds won't help; it comes back over hours
                    raise QuotaExhausted(f"{type(e).__name__}: {e}") from e
                if attempt == self.max_retries:
                    raise LLMInfraError(f"{type(e).__name__} after {attempt + 1} tries: {e}") from e
                backoff = min(60.0, 2**attempt) * (0.5 + random.random() / 2)
                self._sleep(max(backoff, _retry_after(e)))
                continue
            except openai.OpenAIError as e:  # 4xx other than 429: a config problem, not the agent
                raise LLMInfraError(f"{type(e).__name__}: {e}") from e
            reply = self._reply(response, time.monotonic() - start)
            wait = start - first_try
            usage = reply.usage.model_copy(update={"retries": attempt, "retry_wait_s": wait})
            return Reply(reply.text, usage, reply.model, reply.finish_reason)
        raise AssertionError("unreachable")

    def _reply(self, response, latency_s: float) -> Reply:
        if not response.choices:
            raise LLMInfraError("the API returned no choices")
        choice = response.choices[0]
        text = choice.message.content or ""
        usage = response.usage
        input_tokens = (usage.prompt_tokens or 0) if usage else 0
        output_tokens = (usage.completion_tokens or 0) if usage else 0
        # Thinking models can leave their reasoning tokens out of completion_tokens (Gemini's
        # endpoint does) while still counting them in the total, and billing them as output.
        total = (getattr(usage, "total_tokens", None) or 0) if usage else 0
        output_tokens = max(output_tokens, total - input_tokens)
        return Reply(
            text=text,
            finish_reason=getattr(choice, "finish_reason", None),
            model=getattr(response, "model", None) or self.model,
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd(self.price, input_tokens, output_tokens),
                latency_s=latency_s,
                calls=1,
            ),
        )


def _retry_after(error: Exception) -> float:
    """Seconds the provider asked us to wait (Retry-After), capped at a minute; 0 if none."""
    response = getattr(error, "response", None)
    value = response.headers.get("retry-after") if response is not None else None
    try:
        return min(60.0, float(value)) if value else 0.0
    except ValueError:
        return 0.0


def _is_daily_quota(error: Exception) -> bool:
    """Groq: "tokens per day (TPD)" or "requests per day (RPD)"; Gemini: "...PerDay..."."""
    text = str(error).lower()
    return isinstance(error, openai.RateLimitError) and (
        "per day" in text or "perday" in text or "(tpd)" in text or "(rpd)" in text
    )
