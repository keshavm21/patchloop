"""Stop conditions (other than SOLVED and MAX_ATTEMPTS, which the loop checks inline) and the
choice of which candidate the hidden tests judge."""

import ast
import hashlib

from ..config import Budget
from ..models import Attempt, Usage
from .feedback import error_signature


def code_hash(code: str) -> str:
    """A hash that ignores comments, blank lines and formatting."""
    try:
        normalized = ast.dump(ast.parse(code))
    except SyntaxError:
        normalized = " ".join(code.split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def no_progress(attempts: list[Attempt]) -> bool:
    """The latest code repeats an earlier attempt's, or the latest error repeats the one before."""
    if len(attempts) < 2:
        return False
    latest, previous = attempts[-1], attempts[-2]
    if latest.code_hash is not None and latest.code_hash in {a.code_hash for a in attempts[:-1]}:
        return True
    return error_signature(latest.result) == error_signature(previous.result)


def over_budget(usage: Usage, elapsed_s: float, budget: Budget) -> str | None:
    if usage.tokens >= budget.max_tokens:
        return f"{usage.tokens} tokens used of {budget.max_tokens}"
    if elapsed_s >= budget.max_seconds:
        return f"{elapsed_s:.0f} s elapsed of {budget.max_seconds:.0f}"
    if budget.max_cost_usd is not None and (usage.cost_usd or 0.0) >= budget.max_cost_usd:
        return f"${usage.cost_usd:.4f} spent of ${budget.max_cost_usd:.4f}"
    return None


def best_attempt(attempts: list[Attempt]) -> Attempt | None:
    """The attempt that ran with the most visible tests passed; the earlier one wins ties.

    Only code that reached the sandbox is eligible: code that failed the syntax or policy check
    never runs, not even against the hidden tests. None means the starting code is judged.
    """
    best = None
    for attempt in attempts:
        if attempt.ran and (best is None or attempt.result.num_passed > best.result.num_passed):
            best = attempt
    return best
