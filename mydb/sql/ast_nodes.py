"""AST node dataclasses — one per SQL construct."""
from dataclasses import dataclass, field
from typing import Any


# ── Literals & references ─────────────────────────────────────────────────────

@dataclass
class IntLit:    value: int
@dataclass
class FloatLit:  value: float
@dataclass
class StrLit:    value: str
@dataclass
class BoolLit:   value: bool
@dataclass
class NullLit:   pass

@dataclass
class ColRef:
    name:  str
    table: str | None = None   # table alias / name prefix

@dataclass
class Star: pass   # SELECT *


# ── Expressions ───────────────────────────────────────────────────────────────

@dataclass
class BinOp:
    op:    str      # =, !=, <, <=, >, >=, +, -, *, /, %, AND, OR, LIKE
    left:  Any
    right: Any

@dataclass
class UnaryOp:
    op:   str   # NOT, -
    expr: Any

@dataclass
class IsNull:
    expr:   Any
    negate: bool = False   # True → IS NOT NULL

@dataclass
class InExpr:
    expr:   Any
    values: list
    negate: bool = False

@dataclass
class BetweenExpr:
    expr:  Any
    lo:    Any
    hi:    Any

@dataclass
class FuncCall:
    name: str
    args: list   # empty list for COUNT(*)

@dataclass
class Alias:
    expr:  Any
    alias: str


# ── Subquery nodes ───────────────────────────────────────────────────────────

@dataclass
class SubqueryRef:
    """FROM (SELECT ...) AS alias  — inline view in the FROM clause."""
    query: Any          # SelectStmt
    alias: str

@dataclass
class ScalarSubquery:
    """(SELECT ...)  used as a scalar expression."""
    query: Any          # SelectStmt

@dataclass
class InSubquery:
    """expr IN (SELECT ...)  /  expr NOT IN (SELECT ...)"""
    expr:   Any
    query:  Any         # SelectStmt
    negate: bool = False

@dataclass
class ExistsExpr:
    """EXISTS (SELECT ...)"""
    query:  Any         # SelectStmt
    negate: bool = False


# ── SELECT ────────────────────────────────────────────────────────────────────

@dataclass
class TableRef:
    name:  str
    alias: str | None = None

@dataclass
class JoinClause:
    join_type: str       # INNER, LEFT, RIGHT, CROSS
    table:     TableRef
    condition: Any

@dataclass
class OrderItem:
    expr: Any
    asc:  bool = True

@dataclass
class UnionStmt:
    selects:     list        # [SelectStmt, ...]
    union_types: list        # ['UNION'|'UNION ALL'|'INTERSECT'|'EXCEPT', ...] len = len(selects)-1

@dataclass
class SelectStmt:
    columns:  list                          # list of expr or Star
    from_:    TableRef | SubqueryRef | None = None
    joins:    list             = field(default_factory=list)
    where:    Any              = None
    group_by: list             = field(default_factory=list)
    having:   Any              = None
    order_by: list             = field(default_factory=list)
    limit:    int | None       = None
    offset:   int              = 0


# ── INSERT ────────────────────────────────────────────────────────────────────

@dataclass
class InsertStmt:
    table:   str
    columns: list[str]
    rows:    list[list]   # list of value lists


# ── UPDATE ────────────────────────────────────────────────────────────────────

@dataclass
class Assignment:
    column: str
    value:  Any

@dataclass
class UpdateStmt:
    table:       str
    assignments: list[Assignment]
    where:       Any = None


# ── DELETE ────────────────────────────────────────────────────────────────────

@dataclass
class DeleteStmt:
    table: str
    where: Any = None


# ── DDL ───────────────────────────────────────────────────────────────────────

@dataclass
class ColumnDefAST:
    name:        str
    type_name:   str
    primary_key: bool   = False
    not_null:    bool   = False
    unique:      bool   = False
    default:     Any    = None

@dataclass
class CreateTableStmt:
    table:         str
    columns:       list[ColumnDefAST]
    if_not_exists: bool = False

@dataclass
class DropTableStmt:
    table:     str
    if_exists: bool = False

@dataclass
class AlterTableStmt:
    table:  str
    action: tuple   # ('ADD_COLUMN', ColumnDefAST) | ('DROP_COLUMN', col_name)
                    # | ('RENAME_COLUMN', old, new) | ('RENAME_TABLE', new_name)

@dataclass
class CreateIndexStmt:
    name:    str
    table:   str
    columns: list[str]
    unique:  bool = False
