from types import SimpleNamespace

import openai
import pytest

from patchloop.config import Price
from patchloop.llm.base import LLMInfraError
from patchloop.llm.cache import CachedClient, cache_key
from patchloop.llm.fake import FakeLLM
from patchloop.llm.openai_compat import OpenAICompatClient

MESSAGES = [{"role": "user", "content": "hi"}]


class StubCompletions:
    """Stands in for client.chat.completions: raises the scripted errors, then answers."""

    def __init__(self, errors=(), total_tokens=None):
        self.errors = list(errors)
        self.calls = 0
        self.total_tokens = total_tokens

    def create(self, **kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="```python\nx = 1\n```"))],
            usage=SimpleNamespace(
                prompt_tokens=1200, completion_tokens=300, total_tokens=self.total_tokens
            ),
        )


def client_with(errors=(), total_tokens=None, **kwargs):
    stub = StubCompletions(errors, total_tokens)
    fake_openai = SimpleNamespace(chat=SimpleNamespace(completions=stub))
    sleeps = []
    client = OpenAICompatClient(
        "some-model", api_key="k", client=fake_openai, sleep=sleeps.append, **kwargs
    )
    return client, stub, sleeps


def api_error(cls, status):
    request = SimpleNamespace(method="POST", url="https://example.invalid")
    response = SimpleNamespace(status_code=status, headers={}, request=request)
    return cls("boom", response=response, body=None)


def test_usage_and_cost():
    client, _, _ = client_with(price=Price(input_per_mtok=0.5, output_per_mtok=2.0))
    reply = client.chat(MESSAGES, temperature=0.0, max_tokens=100)
    assert reply.text.startswith("```python")
    assert (reply.usage.input_tokens, reply.usage.output_tokens) == (1200, 300)
    assert reply.usage.cost_usd == pytest.approx((1200 * 0.5 + 300 * 2.0) / 1e6)


def test_cost_is_unknown_without_a_price():
    client, _, _ = client_with()
    assert client.chat(MESSAGES, temperature=0.0, max_tokens=100).usage.cost_usd is None


def test_retries_429_and_5xx_with_backoff():
    errors = [api_error(openai.RateLimitError, 429), api_error(openai.InternalServerError, 503)]
    client, stub, sleeps = client_with(errors)
    reply = client.chat(MESSAGES, temperature=0.0, max_tokens=100)
    assert stub.calls == 3
    assert len(sleeps) == 2 and 0.5 <= sleeps[0] <= 1.0 and 1.0 <= sleeps[1] <= 2.0
    assert reply.usage.retries == 2


def test_gives_up_with_an_infra_error():
    errors = [api_error(openai.RateLimitError, 429)] * 3
    client, stub, _ = client_with(errors, max_retries=2)
    with pytest.raises(LLMInfraError, match="RateLimitError after 3 tries"):
        client.chat(MESSAGES, temperature=0.0, max_tokens=100)


def test_bad_request_is_an_infra_error_without_retries():
    client, stub, _ = client_with([api_error(openai.BadRequestError, 400)])
    with pytest.raises(LLMInfraError):
        client.chat(MESSAGES, temperature=0.0, max_tokens=100)
    assert stub.calls == 1


def test_cache_key_includes_the_repeat_index():
    base = cache_key("m", MESSAGES, 0.0, 100, repeat=0)
    assert base == cache_key("m", MESSAGES, 0.0, 100, repeat=0)
    assert base != cache_key("m", MESSAGES, 0.0, 100, repeat=1)
    assert base != cache_key("m", MESSAGES, 0.2, 100, repeat=0)
    assert base != cache_key("other", MESSAGES, 0.0, 100, repeat=0)


def test_cache_serves_repeats_independently(tmp_path):
    inner = FakeLLM(["first", "second", "third"])
    cached = CachedClient(inner, tmp_path)
    r0 = cached.chat(MESSAGES, temperature=0.0, max_tokens=100, repeat=0)
    r1 = cached.chat(MESSAGES, temperature=0.0, max_tokens=100, repeat=1)
    again = cached.chat(MESSAGES, temperature=0.0, max_tokens=100, repeat=0)
    assert (r0.text, r1.text, again.text) == ("first", "second", "first")
    assert len(inner.calls) == 2
    assert again.usage.cached_calls == 1 and again.usage.tokens == r0.usage.tokens


def test_hidden_thinking_tokens_count_as_output():
    # Gemini's endpoint: prompt 1200 + completion 300, but a total of 2000.
    client, _, _ = client_with(total_tokens=2000)
    usage = client.chat(MESSAGES, temperature=0.0, max_tokens=100).usage
    assert (usage.input_tokens, usage.output_tokens) == (1200, 800)
