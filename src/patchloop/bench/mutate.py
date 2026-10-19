"""AST mutation operators for MutBench. Each operator numbers its mutation sites in a fixed
traversal order; mutating site k gives one mutant, so every mutant is reproducible from
(source, operator, k)."""

import ast
import copy


class Operator(ast.NodeTransformer):
    """Mutates the k-th site it visits; counts every site in `seen`."""

    name = ""

    def __init__(self, k: int) -> None:
        self.k, self.seen = k, 0
        self.applied = False

    def _site(self) -> bool:
        """Call once per candidate site; true when this is the site to mutate."""
        hit = self.seen == self.k
        self.seen += 1
        if hit:
            self.applied = True
        return hit


class FlipComparison(Operator):
    """< ↔ <=, > ↔ >=, == ↔ !=, in ↔ not in, is ↔ is not."""

    name = "flip_comparison"
    SWAP = {
        ast.Lt: ast.LtE,
        ast.LtE: ast.Lt,
        ast.Gt: ast.GtE,
        ast.GtE: ast.Gt,
        ast.Eq: ast.NotEq,
        ast.NotEq: ast.Eq,
        ast.In: ast.NotIn,
        ast.NotIn: ast.In,
        ast.Is: ast.IsNot,
        ast.IsNot: ast.Is,
    }

    def visit_Compare(self, node: ast.Compare):
        self.generic_visit(node)
        for i, op in enumerate(node.ops):
            if type(op) in self.SWAP and self._site():
                node.ops[i] = self.SWAP[type(op)]()
        return node


class SwapArithmetic(Operator):
    """+ ↔ -, // ↔ /, * → +."""

    name = "swap_arithmetic"
    SWAP = {
        ast.Add: ast.Sub,
        ast.Sub: ast.Add,
        ast.FloorDiv: ast.Div,
        ast.Div: ast.FloorDiv,
        ast.Mult: ast.Add,
    }

    def visit_BinOp(self, node: ast.BinOp):
        self.generic_visit(node)
        if type(node.op) in self.SWAP and self._site():
            node.op = self.SWAP[type(node.op)]()
        return node

    def visit_AugAssign(self, node: ast.AugAssign):
        self.generic_visit(node)
        if type(node.op) in self.SWAP and self._site():
            node.op = self.SWAP[type(node.op)]()
        return node


class ShiftBound(Operator):
    """range(..., n) → range(..., n - 1), and a[i] → a[i + 1] (reads only)."""

    name = "shift_bound"

    def visit_Call(self, node: ast.Call):
        self.generic_visit(node)
        is_range = isinstance(node.func, ast.Name) and node.func.id == "range"
        if is_range and 1 <= len(node.args) <= 2 and not node.keywords and self._site():
            stop = node.args[-1]
            node.args[-1] = ast.BinOp(left=stop, op=ast.Sub(), right=ast.Constant(1))
        return node

    def visit_Subscript(self, node: ast.Subscript):
        self.generic_visit(node)
        index = node.slice
        simple = isinstance(index, ast.Name) or (
            isinstance(index, ast.Constant) and isinstance(index.value, int)
        )
        if isinstance(node.ctx, ast.Load) and simple and self._site():
            node.slice = ast.BinOp(left=index, op=ast.Add(), right=ast.Constant(1))
        return node


class SwapBoolean(Operator):
    """and ↔ or, and dropping a `not`."""

    name = "swap_boolean"

    def visit_BoolOp(self, node: ast.BoolOp):
        self.generic_visit(node)
        if self._site():
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        return node

    def visit_UnaryOp(self, node: ast.UnaryOp):
        self.generic_visit(node)
        if isinstance(node.op, ast.Not) and self._site():
            return node.operand
        return node


class WrongVariable(Operator):
    """A read of a local name becomes a read of the next local name (sorted) in that function."""

    name = "wrong_variable"

    def visit_FunctionDef(self, node: ast.FunctionDef):
        names = sorted(_local_names(node))
        if len(names) >= 2:
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Load)
                    and child.id in names
                ):
                    if self._site():
                        child.id = names[(names.index(child.id) + 1) % len(names)]
        return node


class DeleteStatement(Operator):
    """Removes an augmented assignment such as `count += 1`."""

    name = "delete_statement"

    def generic_visit(self, node):
        for field, value in ast.iter_fields(node):
            if isinstance(value, list) and value and all(isinstance(s, ast.stmt) for s in value):
                kept = []
                for stmt in value:
                    if isinstance(stmt, ast.AugAssign) and self._site():
                        continue
                    kept.append(self.visit(stmt))
                setattr(node, field, kept or [ast.Pass()])
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        self.visit(item)
            elif isinstance(value, ast.AST):
                self.visit(value)
        return node


class DropGuard(Operator):
    """Removes an early exit: an `if` with no `else` whose body is one return or raise."""

    name = "drop_guard"

    def generic_visit(self, node):
        for field, value in ast.iter_fields(node):
            if isinstance(value, list) and value and all(isinstance(s, ast.stmt) for s in value):
                kept = []
                for stmt in value:
                    guard = (
                        isinstance(stmt, ast.If)
                        and not stmt.orelse
                        and len(stmt.body) == 1
                        and isinstance(stmt.body[0], (ast.Return, ast.Raise))
                    )
                    if guard and self._site():
                        continue
                    kept.append(self.visit(stmt))
                setattr(node, field, kept or [ast.Pass()])
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        self.visit(item)
            elif isinstance(value, ast.AST):
                self.visit(value)
        return node


OPERATORS: list[type[Operator]] = [
    FlipComparison,
    SwapArithmetic,
    ShiftBound,
    SwapBoolean,
    WrongVariable,
    DeleteStatement,
    DropGuard,
]


def normalize(source: str) -> str:
    """The source as ast.unparse writes it, so a mutant differs only at the mutation."""
    return ast.unparse(ast.parse(source)) + "\n"


def all_mutants(source: str, operator: type[Operator]) -> list[tuple[int, str]]:
    """(site, mutant source) for every site of `operator`, skipping no-op mutations."""
    tree = ast.parse(source)
    original = ast.dump(tree)
    mutants, k = [], 0
    while True:
        mutator = operator(k)
        mutated = mutator.visit(copy.deepcopy(tree))
        if not mutator.applied:
            return mutants
        mutated = ast.fix_missing_locations(mutated)
        if ast.dump(mutated) != original:
            text = ast.unparse(mutated) + "\n"
            try:
                ast.parse(text)
            except SyntaxError:
                pass
            else:
                mutants.append((k, text))
        k += 1


def _local_names(func: ast.FunctionDef) -> set[str]:
    args = func.args
    names = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    names |= {a.arg for a in (args.vararg, args.kwarg) if a}
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
    return names
