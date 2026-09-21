"""SQL parser — uses Lark to turn SQL strings into AST nodes."""
import os
from lark import Lark, Transformer, v_args
from .ast_nodes import (
    IntLit, FloatLit, StrLit, BoolLit, NullLit,
    ColRef, Star, BinOp, UnaryOp, IsNull, InExpr, BetweenExpr,
    FuncCall, Alias, TableRef, JoinClause, OrderItem, Assignment,
    ColumnDefAST, CreateTableStmt, DropTableStmt, AlterTableStmt, CreateIndexStmt,
    SelectStmt, UnionStmt, InsertStmt, UpdateStmt, DeleteStmt,
    SubqueryRef, ScalarSubquery, InSubquery, ExistsExpr,
)

_GRAMMAR_PATH = os.path.join(os.path.dirname(__file__), "grammar.lark")
with open(_GRAMMAR_PATH, "r", encoding="utf-8") as _f:
    _GRAMMAR = _f.read()

_parser = Lark(_GRAMMAR, parser="earley", ambiguity="resolve")


@v_args(inline=True)
class _ASTBuilder(Transformer):

    # ── Literals ──────────────────────────────────────────────────────────────

    def int_lit(self, tok):    return IntLit(int(tok))
    def float_lit(self, tok):  return FloatLit(float(tok))
    def str_lit(self, tok):
        s = str(tok)
        if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
            return StrLit(s[1:-1])
        return StrLit(s)
    def true_lit(self):        return BoolLit(True)
    def false_lit(self):       return BoolLit(False)
    def null_lit(self):        return NullLit()
    def literal(self, v):      return v

    # ── References ────────────────────────────────────────────────────────────

    def col_ref(self, name):                return ColRef(str(name))
    def col_ref_qualified(self, tbl, col):  return ColRef(str(col), str(tbl))
    def select_star(self, *_):              return [Star()]

    # ── Expressions ───────────────────────────────────────────────────────────

    def paren_expr(self, e):        return e
    def negate(self, e):            return UnaryOp("-", e)
    def not_expr_op(self, kw, e):   return UnaryOp("NOT", e)
    def not_expr(self, e):          return e   # passthrough
    def primary(self, child):       return child

    def binary_cmp(self, left, op, right): return BinOp(op, left, right)
    def eq(self):   return "="
    def neq(self):  return "!="
    def lt(self):   return "<"
    def lte(self):  return "<="
    def gt(self):   return ">"
    def gte(self):  return ">="

    def is_null(self, e):     return IsNull(e, negate=False)
    def is_not_null(self, e): return IsNull(e, negate=True)
    def like_expr(self, e, pat): return BinOp("LIKE", e, StrLit(str(pat)[1:-1]))
    def in_expr(self, e, *vals):     return InExpr(e, list(vals), negate=False)
    def not_in_expr(self, e, *vals): return InExpr(e, list(vals), negate=True)
    def between_expr(self, e, lo, hi): return BetweenExpr(e, lo, hi)

    def or_expr(self, *args):
        result = args[0]
        for right in args[1:]:
            result = BinOp("OR", result, right)
        return result

    def and_expr(self, *args):
        result = args[0]
        for right in args[1:]:
            result = BinOp("AND", result, right)
        return result

    def ADDOP(self, tok): return str(tok)
    def MULOP(self, tok): return str(tok)
    def MINUS(self, tok): return str(tok)
    def STAR(self, tok):  return Star()

    def add_expr(self, *args): return self._left_assoc(args)
    def mul_expr(self, *args): return self._left_assoc(args)

    def _left_assoc(self, args):
        if len(args) == 1:
            return args[0]
        result = args[0]
        i = 1
        while i < len(args):
            op    = str(args[i])
            right = args[i + 1]
            result = BinOp(op, result, right)
            i += 2
        return result

    def unary_expr(self, e): return e
    def compare_expr(self, e): return e
    def expr(self, e):  return e

    def func_call(self, name, *args):
        clean   = [a for a in args if a is not None and not isinstance(a, Star)]
        is_star = any(isinstance(a, Star) for a in args)
        result  = FuncCall(str(name).upper(), clean)
        if is_star:
            result.args = [Star()]
        return result

    # ── UNION / INTERSECT / EXCEPT ────────────────────────────────────────────

    def union_all(self):      return 'UNION ALL'
    def union_distinct(self): return 'UNION'
    def intersect_op(self):   return 'INTERSECT'
    def except_op(self):      return 'EXCEPT'

    def query(self, *args):
        if len(args) == 1:
            return args[0]   # single SELECT — pass through unchanged
        selects     = [args[i] for i in range(0, len(args), 2)]
        union_types = [args[i] for i in range(1, len(args), 2)]
        return UnionStmt(selects, union_types)

    # ── SELECT ────────────────────────────────────────────────────────────────

    def select_cols(self, *items):  return list(items)
    def select_item(self, *args):
        if len(args) == 1:
            return args[0]
        expr, alias = args[0], str(args[1])
        return Alias(expr, alias)

    def table_name_qual(self, *parts):
        return ".".join(str(p) for p in parts)

    def table_name_ref(self, name, alias=None):
        return TableRef(str(name), str(alias) if alias else None)

    def subquery_ref(self, query, alias):
        return SubqueryRef(query, str(alias))

    def scalar_subquery(self, query):
        return ScalarSubquery(query)

    def in_subquery(self, expr, query):
        return InSubquery(expr, query, negate=False)

    def not_in_subquery(self, expr, query):
        return InSubquery(expr, query, negate=True)

    def exists_expr(self, query):
        return ExistsExpr(query, negate=False)

    def join_clause(self, jtype, tref, cond):
        return JoinClause(str(jtype).upper().strip() or "INNER", tref, cond)

    def join_type(self, *args):
        return str(args[0]).upper() if args else ""

    def JOIN_DIR(self, tok):
        return str(tok).upper()

    def ORDER_DIR(self, tok):
        return str(tok).upper()

    def where_clause(self, expr):   return ('where', expr)
    def group_clause(self, *exprs): return list(exprs)
    def having_clause(self, expr):  return ('having', expr)

    def order_clause(self, *items): return list(items)
    def order_item(self, expr, direction=None):
        asc = str(direction).upper() != "DESC" if direction else True
        return OrderItem(expr, asc)

    def limit_clause(self, n, offset=None):
        return (int(str(n)), int(str(offset)) if offset else 0)

    def select_stmt(self, cols, *rest):
        stmt = SelectStmt(columns=cols)
        for item in rest:
            if isinstance(item, (TableRef, SubqueryRef)):
                stmt.from_ = item
            elif isinstance(item, JoinClause):
                stmt.joins.append(item)
            elif isinstance(item, list) and item and isinstance(item[0], OrderItem):
                stmt.order_by = item
            elif isinstance(item, list):
                stmt.group_by = item
            elif isinstance(item, tuple) and isinstance(item[0], str):
                if item[0] == 'where':
                    stmt.where = item[1]
                else:
                    stmt.having = item[1]
            elif isinstance(item, tuple):   # (limit, offset) — both ints
                stmt.limit, stmt.offset = item
        return stmt

    # ── INSERT ────────────────────────────────────────────────────────────────

    def row_values(self, *lits): return list(lits)

    def insert_stmt(self, table, *rest):
        # rest = col_name tokens... then row_values trees
        cols = []
        rows = []
        for item in rest:
            if isinstance(item, list):
                rows.append([self._lit_value(v) for v in item])
            else:
                cols.append(str(item))
        return InsertStmt(str(table), cols, rows)

    def _lit_value(self, node):
        if isinstance(node, IntLit):   return node.value
        if isinstance(node, FloatLit): return node.value
        if isinstance(node, StrLit):   return node.value
        if isinstance(node, BoolLit):  return node.value
        if isinstance(node, NullLit):  return None
        return node

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def assignment(self, col, expr): return Assignment(str(col), expr)

    def update_stmt(self, table, *rest):
        assignments = [r for r in rest if isinstance(r, Assignment)]
        where_tag   = next((r for r in rest if not isinstance(r, Assignment)), None)
        where       = where_tag[1] if isinstance(where_tag, tuple) else where_tag
        return UpdateStmt(str(table), assignments, where)

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_stmt(self, table, where=None):
        where = where[1] if isinstance(where, tuple) else where
        return DeleteStmt(str(table), where)

    # ── DDL ───────────────────────────────────────────────────────────────────

    def col_def(self, name, type_name, *constraints):
        cdef = ColumnDefAST(str(name), str(type_name).upper())
        for c in constraints:
            if c == "PK":   cdef.primary_key = True; cdef.not_null = True
            elif c == "NN": cdef.not_null = True
            elif c == "UQ": cdef.unique = True
            elif isinstance(c, tuple) and c[0] == "DEFAULT":
                cdef.default = c[1]
        return cdef

    def type_name(self, *toks):      return str(toks[0])
    def pk_constraint(self):         return "PK"
    def notnull_constraint(self):    return "NN"
    def unique_constraint(self):     return "UQ"
    def default_constraint(self, v): return ("DEFAULT", self._lit_value(v))
    def col_constraint(self, v):     return v

    def if_not_exists(self): return True
    def if_exists(self):     return True

    def create_table_stmt(self, *args):
        ine  = any(a is True for a in args)
        name = next((str(a) for a in args if a is not True and not isinstance(a, ColumnDefAST)), None)
        cols = [a for a in args if isinstance(a, ColumnDefAST)]
        return CreateTableStmt(name, cols, if_not_exists=ine)

    def drop_table_stmt(self, *args):
        ie   = any(a is True for a in args)
        name = next((str(a) for a in args if a is not True), None)
        return DropTableStmt(name, if_exists=ie)

    def alter_add_col(self, col_def):
        return ('ADD_COLUMN', col_def)

    def alter_drop_col(self, col_name):
        return ('DROP_COLUMN', str(col_name))

    def alter_rename_col(self, old_name, new_name):
        return ('RENAME_COLUMN', str(old_name), str(new_name))

    def alter_rename_table(self, new_name):
        return ('RENAME_TABLE', str(new_name))

    def alter_table_stmt(self, table_name, action):
        return AlterTableStmt(str(table_name), action)

    def create_index_stmt(self, *args):
        toks   = list(args)
        unique = False
        name   = str(toks[0])
        table  = str(toks[1])
        cols   = [str(t) for t in toks[2:]]
        return CreateIndexStmt(name, table, cols, unique)

    # ── Top level ─────────────────────────────────────────────────────────────

    def statement(self, s): return s
    def start(self, *stmts): return list(stmts)


_builder = _ASTBuilder()


def parse(sql: str) -> list:
    """Parse SQL string → list of AST statement nodes."""
    tree = _parser.parse(sql.strip())
    return _builder.transform(tree)


def parse_one(sql: str):
    """Parse a single SQL statement."""
    stmts = parse(sql)
    if not stmts:
        raise ValueError("Empty SQL")
    return stmts[0]
