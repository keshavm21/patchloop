"""The repair loop with a scripted model and a fake sandbox: one test per stop reason, plus the
paths around them (parse and syntax failures, best-so-far, regressions, explanations)."""

from scripted import failed, passed, reply_with

from patchloop.agent.loop import solve
from patchloop.config import AgentConfig, Budget
from patchloop.llm.base import LLMInfraError
from patchloop.llm.fake import FakeLLM
from patchloop.models import Status, StopReason
from patchloop.safety.base import PolicyResult
from patchloop.sandbox.docker_runner import SandboxInfraError
from patchloop.sandbox.fake import FakeSandbox
from patchloop.tracing import Tracer

FIXED = (
    "def second_largest(nums):\n"
    "    uniq = sorted(set(nums))\n"
    "    return uniq[-2] if len(uniq) >= 2 else None\n"
)
STILL_BUGGY = "def second_largest(nums):\n    return sorted(set(nums))[-2]\n"
OTHER_BUGGY = "def second_largest(nums):\n    return max(nums)\n"
THIRD_BUGGY = "def second_largest(nums):\n    return min(nums)\n"

CFG = AgentConfig(explain_failures=False)


def sandbox_for(task, visible: dict, hidden=None) -> FakeSandbox:
    """Visible results by code; every hidden run gets `hidden` (default: passed)."""

    def run(code, tests_dir):
        if tests_dir == task.hidden_dir:
            return hidden or passed(9)
        return visible[code]

    return FakeSandbox(run)


def run(task, replies, visible, cfg=CFG, hidden=None, **kwargs):
    llm = FakeLLM(replies)
    sandbox = sandbox_for(task, visible, hidden)
    rec = solve(task, cfg, llm, sandbox, **kwargs)
    return rec, llm, sandbox


def test_solves_on_second_attempt(task):
    rec, llm, sandbox = run(
        task,
        [reply_with(STILL_BUGGY), reply_with(FIXED)],
        {STILL_BUGGY: failed("test_single_element", exception="IndexError"), FIXED: passed()},
    )
    assert rec.stop_reason is StopReason.SOLVED
    assert len(rec.attempts) == 2
    assert rec.final_attempt == 2
    assert rec.solved
    # The hidden tests judged the fixed code, and the second prompt carried the first failure.
    assert sandbox.runs[-1] == (FIXED, task.hidden_dir)
    second_prompt = llm.calls[1][1]["content"]
    assert '<execution_output attempt="1">' in second_prompt
    assert "IndexError" in second_prompt


def test_hidden_tests_are_never_shown_or_run_during_attempts(task):
    rec, llm, sandbox = run(
        task,
        [reply_with(STILL_BUGGY), reply_with(OTHER_BUGGY), reply_with(THIRD_BUGGY)],
        {
            STILL_BUGGY: failed("test_single_element"),
            OTHER_BUGGY: failed("test_basic", "test_single_element"),
            THIRD_BUGGY: failed("test_basic", "test_negatives"),
        },
        hidden=failed("test_single_element", expected=9),
    )
    hidden_source = next(task.hidden_dir.glob("*.py")).read_text()
    prompts = "\n".join(m["content"] for call in llm.calls for m in call)
    assert "test_all_equal" in hidden_source and "test_all_equal" not in prompts
    assert [tests for _, tests in sandbox.runs[:-1]] == [task.visible_dir] * 3
    assert sandbox.runs[-1][1] == task.hidden_dir


def test_stops_when_stuck(task):
    rec, _, _ = run(
        task, [reply_with(STILL_BUGGY)] * 3, {STILL_BUGGY: failed("test_single_element")}
    )
    assert rec.stop_reason is StopReason.NO_PROGRESS
    assert len(rec.attempts) == 2


def test_same_code_with_different_formatting_is_no_progress(task):
    reformatted = "def second_largest(nums):  # try again\n\n    return sorted(set(nums))[-2]\n"
    rec, _, _ = run(
        task,
        [reply_with(STILL_BUGGY), reply_with(reformatted)],
        {STILL_BUGGY: failed("test_single_element"), reformatted: failed("test_basic")},
    )
    assert rec.stop_reason is StopReason.NO_PROGRESS


def test_same_error_twice_is_no_progress(task):
    rec, _, _ = run(
        task,
        [reply_with(STILL_BUGGY), reply_with(OTHER_BUGGY), reply_with(FIXED)],
        {
            STILL_BUGGY: failed("test_single_element", exception="IndexError"),
            OTHER_BUGGY: failed("test_single_element", exception="IndexError"),
        },
    )
    assert rec.stop_reason is StopReason.NO_PROGRESS
    assert len(rec.attempts) == 2


def test_max_attempts_and_best_so_far(task):
    rec, _, sandbox = run(
        task,
        [reply_with(STILL_BUGGY), reply_with(OTHER_BUGGY), reply_with(THIRD_BUGGY)],
        {
            STILL_BUGGY: failed("test_basic", "test_single_element"),  # 2 passed
            OTHER_BUGGY: failed("test_single_element"),  # 3 passed: the best
            THIRD_BUGGY: failed("test_duplicates"),  # 3 passed: a tie, so the earlier wins
        },
        hidden=failed("test_single_element", expected=9),
    )
    assert rec.stop_reason is StopReason.MAX_ATTEMPTS
    assert len(rec.attempts) == 3
    assert rec.final_attempt == 2
    assert sandbox.runs[-1] == (OTHER_BUGGY, task.hidden_dir)
    assert not rec.solved


def test_token_budget(task):
    llm = FakeLLM([reply_with(STILL_BUGGY), reply_with(FIXED)], tokens=20_000)
    sandbox = sandbox_for(task, {STILL_BUGGY: failed("test_single_element"), FIXED: passed()})
    rec = solve(task, CFG, llm, sandbox)
    assert rec.stop_reason is StopReason.BUDGET_EXCEEDED
    assert len(rec.attempts) == 1
    assert rec.usage.tokens == 40_000


def test_wall_clock_budget(task):
    ticks = iter(range(0, 1000, 100))  # each clock() call is 100 s later
    cfg = AgentConfig(explain_failures=False, budget=Budget(max_seconds=150))
    rec, _, _ = run(
        task,
        [reply_with(STILL_BUGGY), reply_with(FIXED)],
        {STILL_BUGGY: failed("test_single_element"), FIXED: passed()},
        cfg=cfg,
        clock=lambda: next(ticks),
    )
    assert rec.stop_reason is StopReason.BUDGET_EXCEEDED
    assert len(rec.attempts) == 1


def test_policy_blocked_twice_stops_and_never_runs(task):
    def block_everything(code):
        return PolicyResult(blocked=["line 1 imports `subprocess`, which is not allowed"])

    rec, llm, sandbox = run(
        task,
        [reply_with(STILL_BUGGY), reply_with(OTHER_BUGGY), reply_with(FIXED)],
        {},
        policy=block_everything,
    )
    assert rec.stop_reason is StopReason.POLICY_BLOCKED
    assert [a.result.status for a in rec.attempts] == [Status.POLICY_BLOCKED] * 2
    # Nothing ran but the hidden tests, on the starting code.
    assert sandbox.runs == [(task.starting_code, task.hidden_dir)]
    assert rec.final_attempt is None
    assert "subprocess" in llm.calls[1][1]["content"]


def test_llm_infra_error(task):
    rec, _, sandbox = run(
        task, [LLMInfraError("429 after 6 tries")], {}, cfg=AgentConfig(explain_failures=True)
    )
    assert rec.stop_reason is StopReason.INFRA_ERROR
    assert rec.infra_error == "429 after 6 tries"
    assert rec.hidden_result is None
    assert rec.failure_explanation is None
    assert sandbox.runs == []


def test_sandbox_infra_error(task):
    def broken(code, tests_dir):
        raise SandboxInfraError("cannot reach Docker")

    rec = solve(task, CFG, FakeLLM([reply_with(FIXED)]), FakeSandbox(broken))
    assert rec.stop_reason is StopReason.INFRA_ERROR
    assert "Docker" in rec.infra_error


def test_parse_failure_is_fed_back_without_running(task):
    rec, llm, sandbox = run(
        task, ["I think the fix is to add a guard.", reply_with(FIXED)], {FIXED: passed()}
    )
    assert rec.stop_reason is StopReason.SOLVED
    assert rec.attempts[0].result.status is Status.PARSE_FAILED
    assert not rec.attempts[0].ran
    assert "exactly one fenced code block" in llm.calls[1][1]["content"]
    assert [code for code, _ in sandbox.runs] == [FIXED, FIXED]  # visible, then hidden


def test_syntax_error_never_reaches_the_sandbox(task):
    broken = "def second_largest(nums)\n    return 1\n"
    rec, llm, sandbox = run(task, [reply_with(broken), reply_with(FIXED)], {FIXED: passed()})
    assert rec.attempts[0].result.status is Status.SYNTAX_ERROR
    assert broken not in [code for code, _ in sandbox.runs]
    assert "SyntaxError at line 1" in llm.calls[1][1]["content"]


def test_regression_is_called_out(task):
    rec, llm, _ = run(
        task,
        [reply_with(STILL_BUGGY), reply_with(OTHER_BUGGY), reply_with(FIXED)],
        {
            STILL_BUGGY: failed("test_single_element"),
            OTHER_BUGGY: failed("test_basic"),
            FIXED: passed(),
        },
    )
    assert rec.attempts[1].regressions == ["test_second_largest::test_basic"]
    third_prompt = llm.calls[2][1]["content"]
    assert "Regression" in third_prompt and "test_basic" in third_prompt
    assert "- attempt 1: TESTS_FAILED (3 of 4 tests passed)" in third_prompt


def test_failure_explanation_when_unsolved(task):
    cfg = AgentConfig(explain_failures=True, max_attempts=1)
    rec, llm, _ = run(
        task,
        [reply_with(STILL_BUGGY), "The guard for short lists is still missing."],
        {STILL_BUGGY: failed("test_single_element")},
        cfg=cfg,
        hidden=failed("test_single_element", expected=9),
    )
    assert rec.failure_explanation == "The guard for short lists is still missing."
    assert len(llm.calls) == 2
    assert rec.usage.calls == 1 and rec.explanation_usage.calls == 1


def test_no_explanation_when_solved_or_switched_off(task):
    replies = [reply_with(FIXED)]
    rec, llm, _ = run(task, replies, {FIXED: passed()}, cfg=AgentConfig(explain_failures=True))
    assert rec.failure_explanation is None and len(llm.calls) == 1


def test_l0_shows_no_feedback(task):
    cfg = AgentConfig(explain_failures=False, feedback="L0")
    rec, llm, _ = run(
        task,
        [reply_with(STILL_BUGGY), reply_with(FIXED)],
        {STILL_BUGGY: failed("test_single_element"), FIXED: passed()},
        cfg=cfg,
    )
    second = llm.calls[1][1]["content"]
    assert "<execution_output" not in second and "Earlier attempts" not in second
    # The model still sees its own latest code.
    assert "return sorted(set(nums))[-2]" in second


def test_reflect_mode(task):
    cfg = AgentConfig(explain_failures=False, reflect=True)
    reply = reply_with(FIXED, before="## Diagnosis\nThere is no guard for short lists.\n\n")
    rec, llm, _ = run(task, [reply], {FIXED: passed()}, cfg=cfg)
    assert '"## Diagnosis"' in llm.calls[0][0]["content"]
    assert rec.attempts[0].diagnosis == "There is no guard for short lists."


def test_trace_records_every_step(task):
    tracer = Tracer(run="examples/second_largest/test")
    run(
        task,
        [reply_with(STILL_BUGGY), reply_with(FIXED)],
        {STILL_BUGGY: failed("test_single_element"), FIXED: passed()},
        tracer=tracer,
    )
    events = [(e["event"], e["attempt"]) for e in tracer.events]
    assert events == [
        ("start", None),
        ("llm_call", 1),
        ("parse", 1),
        ("policy_check", 1),
        ("sandbox_run", 1),
        ("feedback", 1),
        ("llm_call", 2),
        ("parse", 2),
        ("policy_check", 2),
        ("sandbox_run", 2),
        ("hidden_verdict", None),
        ("stop", None),
    ]
    assert tracer.events[0]["prompt_version"] == "v1"
    assert tracer.events[-1]["reason"] == StopReason.SOLVED


def test_time_lost_to_rate_limits_does_not_count_against_the_budget(task):
    ticks = iter(range(0, 10_000, 100))  # each clock() call is 100 s later

    class RateLimited(FakeLLM):
        def chat(self, *args, **kwargs):
            reply = super().chat(*args, **kwargs)
            usage = reply.usage.model_copy(update={"retries": 3, "retry_wait_s": 1000.0})
            return type(reply)(text=reply.text, usage=usage, model=reply.model)

    cfg = AgentConfig(explain_failures=False, budget=Budget(max_seconds=150))
    llm = RateLimited([reply_with(STILL_BUGGY), reply_with(FIXED)])
    sandbox = sandbox_for(task, {STILL_BUGGY: failed("test_single_element"), FIXED: passed()})
    rec = solve(task, cfg, llm, sandbox, clock=lambda: next(ticks))
    assert rec.stop_reason is StopReason.SOLVED
    assert rec.usage.retries == 6
