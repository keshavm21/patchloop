"""The interface of the static policy check (§7.1). The checker itself arrives in Phase 5;
until then the loop uses `allow_all`."""

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PolicyResult:
    blocked: list[str] = field(default_factory=list)  # each one stops the code from running
    flagged: list[str] = field(default_factory=list)  # recorded, but the code still runs


PolicyCheck = Callable[[str], PolicyResult]


def allow_all(code: str) -> PolicyResult:
    return PolicyResult()
