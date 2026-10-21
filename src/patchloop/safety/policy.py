"""The static policy check (§7.1): parse with `ast` on the host, run nothing, and compare what the
code imports and calls against the rules in policy.yaml. It is defense in depth. Names built from
strings get past it; the sandbox is the boundary. Blocked code never runs, and the messages say
what to change, so the loop can feed them back like a test failure."""

import ast
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path

import yaml

from .base import PolicyCheck, PolicyResult

POLICY_FILE = Path(__file__).with_name("policy.yaml")


@lru_cache(maxsize=1)
def load_rules(path: Path = POLICY_FILE) -> dict:
    return yaml.safe_load(path.read_text())


def _matches(name: str, patterns: list[str]) -> bool:
    """`name` equals a pattern or sits under it: `os.environ.get` matches `os.environ`."""
    parts = name.split(".")
    prefixes = (".".join(parts[: i + 1]) for i in range(len(parts)))
    return any(fnmatchcase(prefix, p) for prefix in prefixes for p in patterns)


def _reason(table: dict[str, list[str]], name: str) -> str | None:
    return next((reason for reason, patterns in table.items() if _matches(name, patterns)), None)


class _Visitor(ast.NodeVisitor):
    def __init__(self, rules: dict):
        self.rules = rules
        self.alias: dict[str, str] = {}  # local name -> the dotted name it stands for
        self.blocked: list[tuple[int, str]] = []
        self.flagged: list[tuple[int, str]] = []

    # -- helpers
    def _add(self, level: str, node: ast.AST, text: str) -> None:
        target = self.blocked if level == "block" else self.flagged
        item = (getattr(node, "lineno", 0), text)
        if item not in target:
            target.append(item)

    def _dotted(self, node: ast.AST) -> str | None:
        """`a.b.c` as written, with the first part replaced by what it was imported as."""
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        head = self.alias.get(node.id, node.id)
        return ".".join([head, *reversed(parts)])

    def _check_module(self, node: ast.AST, module: str, shown: str) -> None:
        for level in ("block", "flag"):
            reason = _reason(self.rules[level].get("modules", {}), module)
            if reason:
                verb = "is not allowed" if level == "block" else "is unusual"
                self._add(
                    level, node, f"line {node.lineno} imports `{shown}`, which {verb} ({reason})"
                )
                return

    def _check_name(self, node: ast.AST, name: str, shown: str) -> None:
        for level in ("block", "flag"):
            reason = _reason(self.rules[level].get("names", {}), name)
            if reason:
                verb = "is not allowed" if level == "block" else "is unusual"
                self._add(
                    level, node, f"line {node.lineno} uses `{shown}`, which {verb} ({reason})"
                )
                return

    # -- imports
    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self._check_module(node, a.name, a.name)
            if a.asname:
                self.alias[a.asname] = a.name
            else:  # `import a.b.c` binds `a`
                top = a.name.split(".")[0]
                self.alias[top] = top

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = ("." * node.level) + (node.module or "")
        for a in node.names:
            full = f"{module}.{a.name}" if module else a.name
            self._check_module(node, module, module)
            self._check_name(node, full, full)
            self.alias[a.asname or a.name] = full

    # -- uses
    def visit_Name(self, node: ast.Name) -> None:
        name = self.alias.get(node.id, node.id)
        if isinstance(node.ctx, ast.Load) and name == node.id:
            self._check_name(node, name, name)  # a bare builtin such as eval or exit
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        dotted = self._dotted(node)
        if dotted:
            self._check_name(node, dotted, dotted)
        if node.attr.startswith("__") and node.attr.endswith("__"):  # x.__subclasses__()
            self._check_name(node, node.attr, node.attr)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in self.rules["block"].get("methods", {}).get("file writes", []):
                self._add(
                    "block",
                    node,
                    f"line {node.lineno} calls `.{func.attr}()`, which "
                    "is not allowed (file writes)",
                )
            if func.attr == "open":
                self._check_open(node)
        elif isinstance(func, ast.Name) and self.alias.get(func.id, func.id) in ("open", "io.open"):
            self._check_open(node)
        self.generic_visit(node)

    def _check_open(self, node: ast.Call) -> None:
        mode = node.args[1] if len(node.args) > 1 else None
        for kw in node.keywords:
            if kw.arg == "mode":
                mode = kw.value
        if mode is None:
            return
        chars = self.rules["block"]["write_modes"]
        if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
            if any(c in mode.value for c in chars):
                self._add(
                    "block",
                    node,
                    f"line {node.lineno} opens a file with mode "
                    f"{mode.value!r}, which is not allowed (file writes)",
                )
        else:
            self._add(
                "flag", node, f"line {node.lineno} opens a file with a mode that isn't a literal"
            )


def check(code: str) -> PolicyResult:
    """Blocked and flagged findings for `code`, in line order. Code that doesn't parse has
    none: the loop reports its syntax error before it gets here."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return PolicyResult()
    visitor = _Visitor(load_rules())
    visitor.visit(tree)
    return PolicyResult(
        blocked=[text for _, text in sorted(visitor.blocked)],
        flagged=[text for _, text in sorted(visitor.flagged)],
    )


policy_check: PolicyCheck = check
