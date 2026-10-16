"""Terminal rendering of trace events, shared by `patchloop solve` (live, one event at a time)
and `patchloop replay` (a whole trace, with code diffs between attempts)."""

import difflib

from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text

LABEL = 10  # width of the left column


class LiveView:
    """A tracer listener that prints a run as it happens."""

    def __init__(self, console: Console, *, show_code: bool = False) -> None:
        self.console = console
        self.show_code = show_code
        self.previous_code: str | None = None
        self.expected: dict = {}

    def __call__(self, event: dict) -> None:
        kind, n = event["event"], event.get("attempt")
        if kind == "start":
            self.expected = event.get("expected") or {}
            self.previous_code = event.get("starting_code")
            visible = self.expected.get("visible", "?")
            self._line("task", f"{event['task_id']}  ({event['config']}, {visible} visible tests)")
            self._line("model", f"{event['model']} · prompts {event['prompt_version']}")
        elif kind == "parse":
            if not event["ok"]:
                self._line(f"attempt {n}", Text(event["error"] or "no code", style="yellow"))
            if event.get("diagnosis"):
                self._line(f"attempt {n}", f'diagnosis: "{_one_line(event["diagnosis"])}"')
            if event["ok"] and self.show_code:
                self._diff(self.previous_code or "", event["code"], n)
            if event["ok"]:
                self.previous_code = event["code"]
        elif kind == "policy_check":
            if event.get("syntax_error"):
                self._line(f"attempt {n}", Text(f"syntax error, {event['syntax_error']}", "yellow"))
            for reason in event.get("blocked") or []:
                self._line(f"attempt {n}", Text(f"blocked: {reason}", style="red"))
        elif kind == "sandbox_run":
            self._line(f"attempt {n}", _run_text(event))
        elif kind == "hidden_verdict":
            self._line("hidden", _run_text(event))
        elif kind == "explanation" and event.get("text"):
            self._line("why", _one_line(event["text"]))
        elif kind == "stop":
            self._line("result", _result_text(event))

    def _line(self, label: str, body: str | Text) -> None:
        line = Text(f"{label:<{LABEL}} ")
        line.append(body if isinstance(body, Text) else Text(body))
        self.console.print(line, highlight=False)

    def _diff(self, before: str, after: str, n: int) -> None:
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile="before",
                tofile=f"attempt {n}",
            )
        )
        if diff:
            self.console.print(
                Syntax(diff, "diff", theme="ansi_dark", background_color="default", word_wrap=True)
            )
        else:
            self._line("", Text("(no change to the code)", style="dim"))


def render_replay(events: list[dict], console: Console) -> None:
    """A finished trace as a timeline, with a diff for each attempt's code."""
    view = LiveView(console, show_code=True)
    for event in events:
        view(event)


def _run_text(event: dict) -> Text:
    ok = event["status"] == "PASSED"
    total = event.get("expected") or event.get("executed")
    text = Text(f"run → {event['passed']}/{total} passed  ")
    text.append("✓" if ok else event["status"], style="green" if ok else "red")
    failures = event.get("failures") or []
    if failures:
        first = failures[0]
        more = f" (+{len(failures) - 1} more)" if len(failures) > 1 else ""
        text.append(f"  {first['exception']} in {first['name'].rsplit('::', 1)[-1]}{more}")
    elif event.get("problems") and not ok:
        text.append(f"  {event['problems'][0]}")
    return text


def _result_text(event: dict) -> Text:
    reason = event["reason"]
    style = "green" if event.get("solved") else "red"
    text = Text(f"{reason}", style=style)
    if not event.get("solved") and reason == "SOLVED":
        text.append(" on the visible tests, but the hidden tests failed")
    cost = event.get("cost_usd")
    cost_text = f" · ${cost:.4f}" if cost is not None else ""
    text.append(f" · {event['tokens']:,} tokens{cost_text} · {event['duration_s']:.1f} s")
    if event.get("infra_error"):
        text.append(f"\n{'':<{LABEL}} infra error: {event['infra_error']}", style="yellow")
    return text


def _one_line(text: str, limit: int = 160) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
