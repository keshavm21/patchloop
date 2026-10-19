import pytest

from patchloop.llm.base import LLMInfraError
from patchloop.llm.fake import FakeLLM
from patchloop.llm.replay import RecordingLLM, ReplayLLM

MESSAGES = [{"role": "user", "content": "fix it"}]


def test_record_then_replay(tmp_path):
    path = tmp_path / "fixtures.jsonl"
    recorder = RecordingLLM(FakeLLM(["first", "second"], model="m"), path)
    recorder.chat(MESSAGES, temperature=0.0, max_tokens=10)
    recorder.chat(MESSAGES, temperature=0.0, max_tokens=10, repeat=1)
    replay = ReplayLLM(path)
    assert replay.model == "m"
    assert replay.chat(MESSAGES, temperature=0.0, max_tokens=10).text == "first"
    reply = replay.chat(MESSAGES, temperature=0.0, max_tokens=10, repeat=1)
    assert reply.text == "second" and reply.usage.cached_calls == 1


def test_a_changed_prompt_fails_loudly(tmp_path):
    path = tmp_path / "fixtures.jsonl"
    RecordingLLM(FakeLLM(["first"]), path).chat(MESSAGES, temperature=0.0, max_tokens=10)
    changed = [{"role": "user", "content": "fix it, please"}]
    with pytest.raises(LLMInfraError, match="re-record"):
        ReplayLLM(path).chat(changed, temperature=0.0, max_tokens=10)


def test_the_demo_fixture_matches_the_current_prompt(task):
    """CI's `make demo` replays this fixture; a prompt change must re-record it."""
    from pathlib import Path

    from patchloop.agent.prompts import build_messages
    from patchloop.config import load_config
    from patchloop.llm.replay import prompt_key

    root = Path(__file__).resolve().parents[2]
    replay = ReplayLLM(root / "tests" / "replay" / "demo.jsonl")
    cfg = load_config(root / "configs" / "full.yaml")
    key = prompt_key(build_messages(task, task.starting_code, [], cfg), 0)
    assert key in replay.replies
