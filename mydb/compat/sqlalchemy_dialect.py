"""
SQLAlchemy 2.0 dialect for myDB.

Usage
-----
    # Option A — explicit registration (no packaging required)
    from mydb.compat.sqlalchemy_dialect import register
    register()

    from sqlalchemy import create_engine, text
    engine = create_engine("mydb:///myapp.db")

    # Option B — if installed as a package (entry point registered)
    engine = create_engine("mydb:///myapp.db")

Connection URL format
---------------------
    mydb:///relative/path.db     relative path
    mydb:////abs/path.db         absolute path (4 slashes on Unix)
    mydb:///C:/path/myapp.db     absolute path on Windows

Supports
--------
- Core: Table, Column, MetaData, select(), insert(), update(), delete()
- ORM:  Session, declarative_base(), query()
- DDL:  create_all(), drop_all(), Table.create()
- Reflection: inspect(engine).get_table_names() / get_columns()

Does NOT support
----------------
- Subqueries in FROM (myDB parser limitation)
- Table-level PRIMARY KEY / UNIQUE constraints in CREATE TABLE DDL
  (use column-level constraints; single-column PKs work fine)
- RETURNING clause
- Sequences / autoincrement (set a PK column and manage ids yourself)
"""
from __future__ import annotations

from sqlalchemy import types as sqltypes
from sqlalchemy.engine import default
from sqlalchemy.sql import compiler

from mydb.storage.serializer import ColType


# ── Type mappings ─────────────────────────────────────────────────────────────

# myDB ColType → SQLAlchemy type class (for reflection)
_COLTYPE_TO_SA: dict[ColType, type] = {
    ColType.INT:    sqltypes.Integer,
    ColType.BIGINT: sqltypes.BigInteger,
    ColType.FLOAT:  sqltypes.Float,
    ColType.BOOL:   sqltypes.Boolean,
    ColType.TEXT:   sqltypes.Text,
    ColType.BLOB:   sqltypes.LargeBinary,
}


# ── Type compiler (SQLAlchemy type → myDB DDL type string) ───────────────────

class MyDBTypeCompiler(compiler.GenericTypeCompiler):
    def visit_INTEGER(self, type_, **kw):      return "INT"
    def visit_BIGINT(self, type_, **kw):       return "BIGINT"
    def visit_SMALLINT(self, type_, **kw):     return "INT"
    def visit_FLOAT(self, type_, **kw):        return "FLOAT"
    def visit_REAL(self, type_, **kw):         return "FLOAT"
    def visit_NUMERIC(self, type_, **kw):      return "FLOAT"
    def visit_DECIMAL(self, type_, **kw):      return "FLOAT"
    def visit_BOOLEAN(self, type_, **kw):      return "BOOL"
    def visit_TEXT(self, type_, **kw):         return "TEXT"
    def visit_VARCHAR(self, type_, **kw):      return "TEXT"
    def visit_CHAR(self, type_, **kw):         return "TEXT"
    def visit_NVARCHAR(self, type_, **kw):     return "TEXT"
    def visit_CLOB(self, type_, **kw):         return "TEXT"
    def visit_BLOB(self, type_, **kw):         return "BLOB"
    def visit_BINARY(self, type_, **kw):       return "BLOB"
    def visit_VARBINARY(self, type_, **kw):    return "BLOB"
    def visit_large_binary(self, type_, **kw): return "BLOB"
    def visit_DATETIME(self, type_, **kw):     return "TEXT"
    def visit_DATE(self, type_, **kw):         return "TEXT"
    def visit_TIME(self, type_, **kw):         return "TEXT"
    def visit_TIMESTAMP(self, type_, **kw):    return "TEXT"
    def visit_JSON(self, type_, **kw):         return "TEXT"
    def visit_unicode(self, type_, **kw):      return "TEXT"
    def visit_unicode_text(self, type_, **kw): return "TEXT"
    def visit_string(self, type_, **kw):       return "TEXT"
    def visit_null(self, type_, **kw):         return "TEXT"


# ── DDL compiler ──────────────────────────────────────────────────────────────

class MyDBDDLCompiler(compiler.DDLCompiler):
    def visit_create_table(self, create, **kw):
        table   = create.element
        preparer = self.preparer

        cols = []
        for col in table.columns:
            col_def = self.get_column_specification(col)
            cols.append(col_def)

        # Inline PK for single-column primary keys; skip separate constraint
        # (myDB grammar doesn't support table-level PRIMARY KEY (...) clauses)
        create_str = (
            f"CREATE TABLE {preparer.format_table(table)} "
            f"({', '.join(cols)})"
        )
        return create_str

    def get_column_specification(self, column, **kw):
        colspec  = f"{self.preparer.format_column(column)} "
        colspec += self.dialect.type_compiler_instance.process(column.type)

        # column-level constraints
        if column.primary_key:
            colspec += " PRIMARY KEY"
        if not column.nullable and not column.primary_key:
            colspec += " NOT NULL"
        if column.unique and not column.primary_key:
            colspec += " UNIQUE"
        if column.server_default is not None:
            colspec += f" DEFAULT {column.server_default.arg}"

        return colspec

    def visit_drop_table(self, drop, **kw):
        table = drop.element
        if_exists = " IF EXISTS" if drop.if_exists else ""
        return f"DROP TABLE{if_exists} {self.preparer.format_table(table)}"


# ── SQL compiler ──────────────────────────────────────────────────────────────

class MyDBCompiler(compiler.SQLCompiler):
    """Thin subclass — uses SA's default qmark behaviour throughout.

    The default SQLCompiler already generates `?` placeholders and maintains
    positiontup for qmark paramstyle; no overrides needed here.
    """


# ── Dialect ───────────────────────────────────────────────────────────────────

class MyDBDialect(default.DefaultDialect):
    name             = "mydb"
    driver           = "mydb"
    paramstyle       = "qmark"

    statement_compiler  = MyDBCompiler
    ddl_compiler        = MyDBDDLCompiler
    type_compiler_cls   = MyDBTypeCompiler

    # Feature flags
    supports_alter               = False
    supports_sequences           = False
    supports_native_boolean      = True
    supports_sane_rowcount       = False
    supports_sane_multi_rowcount = False
    supports_default_values      = False
    supports_unicode_statements  = True
    supports_unicode_binds       = True
    returns_unicode_strings      = True
    description_encoding         = None
    postfetch_lastrowid          = False
    supports_statement_cache     = False  # disable SA compile caching

    # ── DBAPI wiring ──────────────────────────────────────────────────────────

    @classmethod
    def import_dbapi(cls):          # SQLAlchemy 2.0
        import mydb
        return mydb

    @classmethod
    def dbapi(cls):                 # SQLAlchemy 1.x compat
        import mydb
        return mydb

    def create_connect_args(self, url):
        db_path = url.database or "mydb.db"
        # SA on Windows prepends "/" before the drive letter: /C:/path → C:/path
        if db_path.startswith("/") and len(db_path) > 2 and db_path[2] == ":":
            db_path = db_path[1:]
        # Return as positional arg — our connect(db_path) takes no keyword args
        return [db_path], {}

    def is_disconnect(self, e, connection, cursor):
        return False

    def do_execute(self, cursor, statement, parameters, context=None):
        if parameters:
            cursor.execute(statement, list(parameters))
        else:
            cursor.execute(statement)

    def do_executemany(self, cursor, statement, parameters, context=None):
        for p in parameters:
            if p:
                cursor.execute(statement, list(p))
            else:
                cursor.execute(statement)

    # ── Catalog access helper ─────────────────────────────────────────────────

    def _catalog(self, sa_connection):
        """Return the myDB SystemCatalog from a SQLAlchemy Connection."""
        # SA 2.0: connection.connection is a pool _ConnectionFairy;
        # .dbapi_connection is the raw DBAPI connection (our mydb.Connection)
        try:
            dbapi_conn = sa_connection.connection.dbapi_connection
        except AttributeError:
            dbapi_conn = sa_connection.connection
        return dbapi_conn._engine._catalog

    # ── Reflection ────────────────────────────────────────────────────────────

    def get_table_names(self, connection, schema=None, **kw):
        return self._catalog(connection).list_tables()

    def get_view_names(self, connection, schema=None, **kw):
        return []

    def has_table(self, connection, table_name, schema=None, **kw):
        return self._catalog(connection).table_exists(table_name.lower())

    def get_columns(self, connection, table_name, schema=None, **kw):
        tschema = self._catalog(connection).get_table(table_name.lower())
        if tschema is None:
            raise Exception(f"Table '{table_name}' not found")
        result = []
        for col in tschema.columns:
            sa_type = _COLTYPE_TO_SA.get(col.col_type, sqltypes.Text)()
            result.append({
                "name":    col.name,
                "type":    sa_type,
                "nullable": col.nullable,
                "default": col.default,
                "autoincrement": False,
                "comment": None,
            })
        return result

    def get_pk_constraint(self, connection, table_name, schema=None, **kw):
        tschema = self._catalog(connection).get_table(table_name.lower())
        if tschema is None:
            return {"constrained_columns": [], "name": None}
        pks = [c.name for c in tschema.columns if c.primary_key]
        return {"constrained_columns": pks, "name": None}

    def get_foreign_keys(self, connection, table_name, schema=None, **kw):
        return []

    def get_unique_constraints(self, connection, table_name, schema=None, **kw):
        tschema = self._catalog(connection).get_table(table_name.lower())
        if tschema is None:
            return []
        return [
            {"name": None, "column_names": [c.name], "duplicates_index": None}
            for c in tschema.columns
            if c.unique and not c.primary_key
        ]

    def get_indexes(self, connection, table_name, schema=None, **kw):
        tschema = self._catalog(connection).get_table(table_name.lower())
        if tschema is None:
            return []
        return [
            {
                "name":         idx.name,
                "column_names": idx.columns,
                "unique":       idx.unique,
            }
            for idx in tschema.indexes
        ]

    def get_check_constraints(self, connection, table_name, schema=None, **kw):
        return []

    def get_schema_names(self, connection, **kw):
        return ["main"]

    @classmethod
    def get_dialect_cls(cls, url):
        return cls


# ── Registration helper ───────────────────────────────────────────────────────

def register():
    """Register the mydb:// URL scheme with SQLAlchemy.

    Call this once at application startup before creating any engine:

        from mydb.compat.sqlalchemy_dialect import register
        register()
        engine = create_engine("mydb:///myapp.db")
    """
    from sqlalchemy.dialects import registry as _reg
    _reg.register("mydb", "mydb.compat.sqlalchemy_dialect", "MyDBDialect")
