"""The repair loop: a plain state machine, no agent framework.

Each attempt builds a prompt, calls the model, parses one code block, checks syntax and policy
on the host (nothing executes there), and runs the visible tests in the sandbox. When a stop
condition fires, the best candidate so far goes to the hidden tests in fresh containers.
"""

import time
from collections.abc import Callable

from ..config import AgentConfig
from ..llm.base import LLMClient, LLMInfraError, QuotaExhausted
from ..models import (
    Attempt,
    ExecutionResult,
    RunRecord,
    Status,
    StopReason,
    Task,
    host_result,
)
from ..safety.base import PolicyCheck, allow_all
from ..sandbox.docker_runner import SandboxInfraError, SandboxUnavailable
from ..sandbox.sandbox import Sandbox
from ..tracing import Tracer
from .feedback import regressions, render, summarize
from .parsing import parse_reply, syntax_error
from .prompts import build_explain_messages, build_messages, prompt_sha
from .stopping import best_attempt, code_hash, no_progress, over_budget


def solve(
    task: Task,
    cfg: AgentConfig,
    llm: LLMClient,
    sandbox: Sandbox,
    *,
    policy: PolicyCheck = allow_all,
    tracer: Tracer | None = None,
    repeat: int = 0,
    clock: Callable[[], float] = time.monotonic,
) -> RunRecord:
    tracer = tracer or Tracer()
    start = clock()
    rec = RunRecord(
        task_id=task.id,
        config=cfg.name,
        repeat=repeat,
        model=llm.model,
        prompt_version=cfg.prompt_version,
    )
    tracer.emit(
        "start",
        task_id=task.id,
        config=cfg.name,
        model=llm.model,
        prompt_version=cfg.prompt_version,
        feedback=cfg.feedback,
        max_attempts=cfg.max_attempts,
        repeat=repeat,
        expected=task.expected_counts.model_dump(),
        starting_code=task.starting_code,
    )
    try:
        reason = _attempts(task, cfg, llm, sandbox, policy, tracer, rec, repeat, start, clock)
        best = best_attempt(rec.attempts)
        rec.final_attempt = best.n if best else None
        final_code = best.code if best else task.starting_code
        rec.hidden_result = sandbox.run(final_code, task.hidden_dir, task.expected_counts.hidden)
        tracer.emit(
            "hidden_verdict", final_attempt=rec.final_attempt, **_run_fields(rec.hidden_result)
        )
    except (QuotaExhausted, SandboxUnavailable):
        raise  # not this task's infra error: the caller stops and resumes later
    except (LLMInfraError, SandboxInfraError) as e:
        reason, rec.infra_error, rec.hidden_result = StopReason.INFRA_ERROR, str(e), None
    rec.stop_reason = reason
    if cfg.explain_failures and reason is not StopReason.INFRA_ERROR and not rec.solved:
        _explain(task, cfg, llm, tracer, rec, repeat)
    rec.duration_s = clock() - start
    tracer.emit(
        "stop",
        reason=reason,
        solved=rec.solved,
        final_attempt=rec.final_attempt,
        infra_error=rec.infra_error,
        tokens=rec.usage.tokens,
        cost_usd=rec.usage.cost_usd,
        duration_s=rec.duration_s,
    )
    return rec


def _attempts(task, cfg, llm, sandbox, policy, tracer, rec, repeat, start, clock) -> StopReason:
    code = task.starting_code
    for n in range(1, cfg.max_attempts + 1):
        # Time lost to the provider's rate limits and outages doesn't count against the agent.
        elapsed = clock() - start - rec.usage.retry_wait_s
        if why := over_budget(rec.usage, elapsed, cfg.budget):
            tracer.emit("budget", n, detail=why)
            return StopReason.BUDGET_EXCEEDED
        if rec.attempts and (shown := render(rec.attempts[-1], cfg.feedback)):
            tracer.emit("feedback", n - 1, level=cfg.feedback, text=shown)

        messages = build_messages(task, code, rec.attempts, cfg)
        reply = llm.chat(
            messages,
            temperature=cfg.model.temperature,
            max_tokens=cfg.model.max_output_tokens,
            repeat=repeat,
        )
        rec.usage += reply.usage
        tracer.emit(
            "llm_call",
            n,
            model=reply.model,
            prompt_version=cfg.prompt_version,
            prompt_sha=prompt_sha(messages),
            input_tokens=reply.usage.input_tokens,
            output_tokens=reply.usage.output_tokens,
            cost_usd=reply.usage.cost_usd,
            latency_s=reply.usage.latency_s,
            retries=reply.usage.retries,
            retry_wait_s=round(reply.usage.retry_wait_s, 3),
            cached=bool(reply.usage.cached_calls),
            finish_reason=reply.finish_reason,
            reply=reply.text,
        )

        parsed = parse_reply(reply.text)
        tracer.emit(
            "parse",
            n,
            ok=parsed.code is not None,
            code=parsed.code,
            diagnosis=parsed.diagnosis,
            error=parsed.error,
        )
        result, ran = _check_and_run(task, parsed.code, parsed.error, policy, sandbox, tracer, n)

        attempt = Attempt(
            n=n,
            reply=reply.text,
            diagnosis=parsed.diagnosis,
            code=parsed.code,
            code_hash=code_hash(parsed.code) if parsed.code is not None else None,
            result=result,
            ran=ran,
            regressions=regressions(rec.attempts, result) if ran else [],
            summary="",
            usage=reply.usage,
            finish_reason=reply.finish_reason,
        )
        attempt.summary = summarize(attempt, "L3")
        rec.attempts.append(attempt)

        if result.passed:
            return StopReason.SOLVED
        blocks = sum(a.result.status is Status.POLICY_BLOCKED for a in rec.attempts)
        if blocks >= cfg.max_policy_blocks:
            return StopReason.POLICY_BLOCKED
        if no_progress(rec.attempts):
            return StopReason.NO_PROGRESS
        if parsed.code is not None:
            code = parsed.code
    return StopReason.MAX_ATTEMPTS


def _check_and_run(
    task, code, parse_error, policy, sandbox, tracer, n
) -> tuple[ExecutionResult, bool]:
    """Host-side checks, then the visible tests. Returns the result and whether the code ran."""
    if code is None:
        return host_result(Status.PARSE_FAILED, parse_error or "no code"), False
    if err := syntax_error(code):
        tracer.emit("policy_check", n, syntax_error=err, blocked=[], flagged=[])
        return host_result(Status.SYNTAX_ERROR, f"SyntaxError at {err}"), False
    verdict = policy(code)
    tracer.emit(
        "policy_check", n, syntax_error=None, blocked=verdict.blocked, flagged=verdict.flagged
    )
    if verdict.blocked:
        return host_result(Status.POLICY_BLOCKED, "; ".join(verdict.blocked)), False
    result = sandbox.run(code, task.visible_dir, task.expected_counts.visible)
    tracer.emit("sandbox_run", n, code_sha=code_hash(code), **_run_fields(result))
    return result, True


def _explain(task, cfg, llm, tracer, rec, repeat) -> None:
    """A short model-written explanation of why an unsolved run failed. Its usage is kept
    apart from the repair attempts', and an API failure here never changes the run's outcome."""
    best = next((a for a in rec.attempts if a.n == rec.final_attempt), None)
    code = best.code if best else task.starting_code
    messages = build_explain_messages(task, code, rec.attempts, cfg)
    try:
        reply = llm.chat(
            messages,
            temperature=cfg.model.temperature,
            max_tokens=300,
            repeat=repeat,
        )
    except LLMInfraError as e:
        tracer.emit("explanation", error=str(e))
        return
    rec.explanation_usage += reply.usage
    rec.failure_explanation = reply.text.strip()
    tracer.emit("explanation", text=rec.failure_explanation, tokens=reply.usage.tokens)


def _run_fields(result: ExecutionResult) -> dict:
    return {
        "status": result.status,
        "passed": result.num_passed,
        "failed": result.num_failed + result.num_errors,
        "executed": result.executed,
        "expected": result.expected,
        "duration_s": round(result.duration_s, 3),
        "oom": result.oom,
        "timed_out": result.timed_out,
        "problems": result.problems,
        "failures": [{"name": f.name, "exception": f.exception} for f in result.failures[:3]],
    }
