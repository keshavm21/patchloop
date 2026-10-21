"""Build the messages for each attempt from the versioned templates in prompts/<version>/.

Each prompt holds the task, the current code, the visible tests, a one-line summary of each
earlier attempt and full feedback on the latest one, so its size stays bounded however many
attempts run. Untrusted text goes inside <task>, <code>, <tests> and <execution_output> tags,
which the system prompt declares to be data.
"""

import functools
import hashlib
import json
from pathlib import Path
from string import Template

from ..config import AgentConfig
from ..llm.base import Message
from ..models import Attempt, Task
from .feedback import escape_data, render, summarize

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


@functools.cache
def template(version: str, name: str) -> Template:
    return Template((PROMPTS_DIR / version / f"{name}.md").read_text())


SYSTEM_BY_DEFENSE = {"D0": "system_d0", "D1": "system_d1", "D2": "system", "D3": "system"}


def build_messages(
    task: Task, code: str, attempts: list[Attempt], cfg: AgentConfig
) -> list[Message]:
    """D0 and D1 (the injection-defense ladder, §7.2) send untrusted text as is, with no data
    tags; D1 adds a rule that it is data. D2 and D3 tag it, so they send the same prompt."""
    version = cfg.prompt_version
    tagged = cfg.defense in ("D2", "D3")
    reflect = template(version, "reflect").template.strip() if cfg.reflect else ""
    system = template(version, SYSTEM_BY_DEFENSE[cfg.defense]).substitute(
        entrypoint=task.entrypoint, reflect=reflect
    )
    esc = escape_data if tagged else (lambda text: text)
    history = feedback = ""
    if attempts:
        lines = [line for a in attempts[:-1] if (line := summarize(a, cfg.feedback))]
        if lines:
            history = "\nEarlier attempts:\n" + "".join(f"- {line}\n" for line in lines)
        if rendered := render(attempts[-1], cfg.feedback, tagged=tagged):
            feedback = f"\nThe result of your last attempt:\n{rendered}\n"
    user = template(version, "task" if tagged else "task_plain").substitute(
        instruction=esc(task.instruction),
        entrypoint=task.entrypoint,
        code=esc(code.rstrip("\n")),
        tests=esc(visible_tests_text(task)),
        history=esc(history),
        feedback=feedback,
    )
    return [{"role": "system", "content": system.strip()}, {"role": "user", "content": user}]


def build_explain_messages(
    task: Task, code: str, attempts: list[Attempt], cfg: AgentConfig
) -> list[Message]:
    """The prompt for the short failure explanation of an unsolved run."""
    version = cfg.prompt_version
    history = "".join(f"- {summarize(a, 'L3')}\n" for a in attempts) or "- no attempts\n"
    user = template(version, "explain").substitute(
        instruction=escape_data(task.instruction),
        code=escape_data(code.rstrip("\n")),
        history=escape_data(history.rstrip("\n")),
        feedback=(render(attempts[-1], "L3") if attempts else None) or "none",
    )
    system = template(version, "explain_system").template.strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def visible_tests_text(task: Task) -> str:
    """The visible test files, each under a `# file:` header. Hidden tests are never read here."""
    parts = []
    for path in sorted(task.visible_dir.rglob("*.py")):
        parts.append(f"# file: {path.relative_to(task.visible_dir)}\n{path.read_text().rstrip()}")
    return "\n\n".join(parts)


def prompt_sha(messages: list[Message]) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()[:16]
