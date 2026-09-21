"""
Expression evaluator — resolves AST expression nodes against a row dict.

Rows are passed as  {col_name: value}  or  {"table.col": value}.
"""
import re
import fnmatch
from mydb.sql.ast_nodes import (
    IntLit, FloatLit, StrLit, BoolLit, NullLit,
    ColRef, BinOp, UnaryOp, IsNull, InExpr, BetweenExpr,
    FuncCall, Alias, Star,
    ScalarSubquery, InSubquery, ExistsExpr,
)


class ExprEvaluator:
    def __init__(self, engine=None, agg_state: dict | None = None):
        self._engine = engine   # Engine reference for subquery execution
        self._agg = agg_state or {}

    def eval(self, node, row: dict):
        t = type(node)

        if t is IntLit:   return node.value
        if t is FloatLit: return node.value
        if t is StrLit:   return node.value
        if t is BoolLit:  return node.value
        if t is NullLit:  return None

        if t is ColRef:
            if node.table:
                key = f"{node.table}.{node.name}"
                if key in row:
                    return row[key]
            # try plain name (case-insensitive)
            name_lower = node.name.lower()
            for k, v in row.items():
                if k.split(".")[-1].lower() == name_lower:
                    return v
            raise KeyError(f"Column '{node.name}' not found in row")

        if t is Alias:
            return self.eval(node.expr, row)

        if t is UnaryOp:
            v = self.eval(node.expr, row)
            if node.op == "-":
                return -v if v is not None else None
            if node.op == "NOT":
                return not self._truthy(v)

        if t is BinOp:
            return self._binop(node, row)

        if t is IsNull:
            v = self.eval(node.expr, row)
            result = v is None
            return (not result) if node.negate else result

        if t is InExpr:
            v      = self.eval(node.expr, row)
            values = [self.eval(lit, row) for lit in node.values]
            result = v in values
            return (not result) if node.negate else result

        if t is BetweenExpr:
            v  = self.eval(node.expr, row)
            lo = self.eval(node.lo, row)
            hi = self.eval(node.hi, row)
            if v is None or lo is None or hi is None:
                return None
            return lo <= v <= hi

        if t is FuncCall:
            return self._func(node, row)

        if t is ScalarSubquery:
            rows = self._engine._exec_query(node.query, outer_row=row)
            if not rows:
                return None
            return list(rows[0].values())[0]

        if t is InSubquery:
            val  = self.eval(node.expr, row)
            rows = self._engine._exec_query(node.query, outer_row=row)
            vals = [list(r.values())[0] for r in rows]
            hit  = val in vals
            return (not hit) if node.negate else hit

        if t is ExistsExpr:
            rows = self._engine._exec_query(node.query, outer_row=row)
            hit  = len(rows) > 0
            return (not hit) if node.negate else hit

        raise NotImplementedError(f"Cannot evaluate node type {t.__name__}")

    # ── Binary operations ─────────────────────────────────────────────────────

    def _binop(self, node: BinOp, row: dict):
        op = node.op
        if op == "AND":
            l = self.eval(node.left, row)
            return self.eval(node.right, row) if self._truthy(l) else False
        if op == "OR":
            l = self.eval(node.left, row)
            return True if self._truthy(l) else self.eval(node.right, row)

        l = self.eval(node.left, row)
        r = self.eval(node.right, row)

        if l is None or r is None:
            return None

        if op == "=":   return l == r
        if op == "!=":  return l != r
        if op == "<":   return l < r
        if op == "<=":  return l <= r
        if op == ">":   return l > r
        if op == ">=":  return l >= r
        if op == "+":   return l + r
        if op == "-":   return l - r
        if op == "*":   return l * r
        if op == "/":
            if r == 0:  raise ZeroDivisionError("Division by zero")
            return l / r
        if op == "%":   return l % r
        if op == "LIKE":
            pattern = str(r).replace("%", "*").replace("_", "?")
            return fnmatch.fnmatchcase(str(l), pattern)

        raise NotImplementedError(f"Unknown operator: {op}")

    # ── Built-in functions ────────────────────────────────────────────────────

    def _func(self, node: FuncCall, row: dict):
        name = node.name.upper()
        args = [self.eval(a, row) for a in node.args if not isinstance(a, Star)]

        if name == "UPPER":   return str(args[0]).upper() if args[0] is not None else None
        if name == "LOWER":   return str(args[0]).lower() if args[0] is not None else None
        if name == "LENGTH":  return len(str(args[0])) if args[0] is not None else None
        if name == "ABS":     return abs(args[0]) if args[0] is not None else None
        if name == "COALESCE":
            for a in args:
                if a is not None:
                    return a
            return None
        if name == "ROUND":
            v = args[0]
            d = int(args[1]) if len(args) > 1 else 0
            return round(v, d) if v is not None else None
        if name in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
            # In HAVING context, agg_row already has the computed value keyed
            # by the function name (stored alongside any alias in _aggregate).
            key = name.lower()
            if key in row:
                return row[key]
            # Outside aggregate context — sentinel for executor-level handling
            return ("__AGG__", name, node.args)

        raise NotImplementedError(f"Unknown function: {name}")

    @staticmethod
    def _truthy(v) -> bool:
        if v is None:   return False
        if v is False:  return False
        if v == 0:      return False
        return True
