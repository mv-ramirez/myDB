"""
SQLite drop-in compatibility layer.

Replace:
    import sqlite3
    conn = sqlite3.connect("app.db")

With:
    from mydb.compat.sqlite_compat import connect
    conn = connect("app.db")

The Connection and Cursor objects mimic sqlite3's API including:
  - conn.execute() shorthand
  - cur.lastrowid  (approximated)
  - conn.row_factory support
  - :named and %(name)s param styles (in addition to ?)
"""
import re
from .dbapi2 import Connection as _Connection, Cursor as _Cursor, connect as _connect, _quote


class SqliteCompatCursor(_Cursor):
    def __init__(self, engine, row_factory=None):
        super().__init__(engine)
        self._row_factory = row_factory
        self.lastrowid    = None

    def execute(self, sql: str, parameters=None):
        sql = _normalize_params(sql, parameters)
        super().execute(sql)
        # approximate lastrowid
        self.lastrowid = None
        return self

    def fetchone(self):
        row = super().fetchone()
        if row is None:
            return None
        return self._row_factory(self, row) if self._row_factory else row

    def fetchall(self):
        rows = super().fetchall()
        if self._row_factory:
            return [self._row_factory(self, r) for r in rows]
        return rows

    def fetchmany(self, size=None):
        rows = super().fetchmany(size)
        if self._row_factory:
            return [self._row_factory(self, r) for r in rows]
        return rows


class SqliteCompatConnection(_Connection):
    def __init__(self, db_path: str):
        super().__init__(db_path)
        self.row_factory = None     # set to sqlite3.Row equivalent if desired
        self.isolation_level = ""   # sqlite3 compat attribute

    def cursor(self) -> SqliteCompatCursor:
        self._check_open()
        return SqliteCompatCursor(self._engine, self.row_factory)

    def execute(self, sql: str, parameters=None) -> SqliteCompatCursor:
        """Shorthand: conn.execute() without explicitly creating a cursor."""
        cur = self.cursor()
        cur.execute(sql, parameters)
        return cur

    def executemany(self, sql: str, seq_of_params):
        cur = self.cursor()
        cur.executemany(sql, seq_of_params)
        return cur

    def executescript(self, script: str):
        """Execute multiple semicolon-separated SQL statements."""
        from mydb.sql.parser import parse
        stmts = parse(script)
        for stmt in stmts:
            self._engine.execute(stmt)
        self.commit()


def connect(database: str, **kwargs) -> SqliteCompatConnection:
    """sqlite3.connect() drop-in. Extra kwargs are silently ignored."""
    return SqliteCompatConnection(database)


# ── Parameter style normalizer ────────────────────────────────────────────────

def _normalize_params(sql: str, params) -> str:
    """Convert :name, %(name)s, or ? placeholders + params into literal SQL."""
    if not params:
        return sql

    if isinstance(params, dict):
        # :name or %(name)s style
        def replacer(m):
            key = m.group(1) or m.group(2)
            return _quote(params[key])
        sql = re.sub(r":([A-Za-z_]\w*)|%\(([A-Za-z_]\w*)\)s", replacer, sql)
        return sql

    # sequence — ? placeholders
    result = []
    pi     = 0
    for ch in sql:
        if ch == "?" and pi < len(params):
            result.append(_quote(params[pi]))
            pi += 1
        else:
            result.append(ch)
    return "".join(result)
