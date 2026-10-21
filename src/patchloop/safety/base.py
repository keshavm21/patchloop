"""The interface of the static policy check (§7.1). The checker is policy.py; the loop uses it
at defense level D3 and `allow_all` below that."""

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PolicyResult:
    blocked: list[str] = field(default_factory=list)  # each one stops the code from running
    flagged: list[str] = field(default_factory=list)  # recorded, but the code still runs


PolicyCheck = Callable[[str], PolicyResult]


def allow_all(code: str) -> PolicyResult:
    return PolicyResult()


def policy_for(defense: str) -> PolicyCheck:
    """The policy check a defense level uses: only D3 runs the static check."""
    if defense != "D3":
        return allow_all
    from .policy import check

    return check
