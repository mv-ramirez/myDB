"""
PEP 249 — Python DB-API 2.0 compliant interface for myDB.

Usage:
    import mydb
    conn = mydb.connect("myapp.db")
    cur  = conn.cursor()
    cur.execute("CREATE TABLE users (id INT, name TEXT)")
    cur.execute("INSERT INTO users (id, name) VALUES (?, ?)", (1, "Alice"))
    conn.commit()
    cur.execute("SELECT * FROM users")
    rows = cur.fetchall()
    conn.close()
"""
from mydb.sql.parser import parse_one, parse
from mydb.executor.engine import Engine
from mydb.sql.ast_nodes import SelectStmt, Star, Alias, ColRef, FuncCall

# ── Module-level constants (PEP 249 required) ─────────────────────────────────

apilevel     = "2.0"
threadsafety = 1       # threads may share the module but not connections
paramstyle   = "qmark" # ? placeholders


# ── Exceptions (PEP 249 hierarchy) ────────────────────────────────────────────

class Error(Exception):           pass
class Warning(Exception):         pass
class InterfaceError(Error):      pass
class DatabaseError(Error):       pass
class InternalError(DatabaseError): pass
class OperationalError(DatabaseError): pass
class ProgrammingError(DatabaseError): pass
class IntegrityError(DatabaseError): pass
class DataError(DatabaseError):   pass
class NotSupportedError(DatabaseError): pass


# ── Type objects (PEP 249 required) ───────────────────────────────────────────

class _DBType:
    def __init__(self, *values): self.values = values
    def __eq__(self, other):     return other in self.values

STRING   = _DBType(str)
BINARY   = _DBType(bytes, bytearray)
NUMBER   = _DBType(int, float)
DATETIME = _DBType()
ROWID    = _DBType()


# ── Connection ────────────────────────────────────────────────────────────────

class Connection:
    def __init__(self, db_path: str):
        self._engine   = Engine(db_path)
        self._closed   = False
        self._autocommit = False

    def cursor(self) -> "Cursor":
        self._check_open()
        return Cursor(self._engine)

    def commit(self):
        self._check_open()
        self._engine._pool.flush_all()

    def rollback(self):
        # Basic: flush clears dirty state; full WAL-based rollback is future work
        self._check_open()

    def close(self):
        if not self._closed:
            self._engine.close()
            self._closed = True

    def __enter__(self):  return self
    def __exit__(self, *_): self.close()

    def _check_open(self):
        if self._closed:
            raise InterfaceError("Connection is closed")


# ── Cursor ────────────────────────────────────────────────────────────────────

class Cursor:
    def __init__(self, engine: Engine):
        self._engine      = engine
        self._results:    list[dict] = []
        self._pos:        int        = 0
        self._description = None
        self.arraysize    = 1
        self.rowcount     = -1

    # ── Description (PEP 249) ─────────────────────────────────────────────────

    @property
    def description(self):
        return self._description

    # ── execute ───────────────────────────────────────────────────────────────

    def execute(self, sql: str, parameters=None):
        sql = self._bind(sql, parameters)
        try:
            stmt = parse_one(sql)
            rows = self._engine.execute(stmt)
        except Exception as e:
            raise OperationalError(str(e)) from e

        self._results    = rows
        self._pos        = 0
        self.rowcount    = len(rows)

        if rows:
            cols = list(rows[0].keys())
            self._description = tuple(
                (c, None, None, None, None, None, True) for c in cols
            )
        elif isinstance(stmt, SelectStmt):
            # Empty SELECT: still mark as SELECT result so SA won't close it
            self._description = self._select_description(stmt)
        else:
            self._description = None

        return self

    def executemany(self, sql: str, seq_of_params):
        for params in seq_of_params:
            self.execute(sql, params)

    # ── fetch ─────────────────────────────────────────────────────────────────

    def fetchone(self):
        if self._pos >= len(self._results):
            return None
        row = self._row_tuple(self._results[self._pos])
        self._pos += 1
        return row

    def fetchmany(self, size: int | None = None):
        size  = size or self.arraysize
        batch = self._results[self._pos: self._pos + size]
        self._pos += len(batch)
        return [self._row_tuple(r) for r in batch]

    def fetchall(self):
        rows      = self._results[self._pos:]
        self._pos = len(self._results)
        return [self._row_tuple(r) for r in rows]

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                break
            yield row

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _row_tuple(row: dict) -> tuple:
        return tuple(row.values())

    @staticmethod
    def _bind(sql: str, params) -> str:
        """Replace ? or :name placeholders with literal values."""
        if not params:
            return sql
        if isinstance(params, dict):
            import re
            def _replacer(m):
                key = m.group(1)
                return _quote(params[key])
            return re.sub(r":([A-Za-z_]\w*)", _replacer, sql)
        result = []
        pi     = 0
        for ch in sql:
            if ch == "?" and pi < len(params):
                result.append(_quote(params[pi]))
                pi += 1
            else:
                result.append(ch)
        return "".join(result)

    def _select_description(self, stmt: SelectStmt):
        """Return a description tuple for an empty SELECT result."""
        if stmt.from_ is None:
            return ()
        schema = self._engine._catalog.get_table(stmt.from_.name)
        cols = stmt.columns
        if not cols or (isinstance(cols[0], Star)):
            if schema:
                return tuple(
                    (c.name.lower(), None, None, None, None, None, True)
                    for c in schema.columns
                )
            return ()
        names = []
        for col in cols:
            if isinstance(col, Star):
                if schema:
                    names.extend(c.name.lower() for c in schema.columns)
            elif isinstance(col, Alias):
                names.append(col.alias.lower())
            elif isinstance(col, ColRef):
                names.append(col.name.lower())
            elif isinstance(col, FuncCall):
                names.append(col.name.lower())
            else:
                names.append("col")
        return tuple((n, None, None, None, None, None, True) for n in names)

    def close(self): pass  # cursors are lightweight; nothing to release


# ── Value quoting ─────────────────────────────────────────────────────────────

def _quote(val) -> str:
    if val is None:          return "NULL"
    if isinstance(val, bool): return "TRUE" if val else "FALSE"
    if isinstance(val, int):  return str(val)
    if isinstance(val, float): return repr(val)
    # string — escape single quotes
    return "'" + str(val).replace("'", "''") + "'"


# ── Module-level connect ──────────────────────────────────────────────────────

def connect(db_path: str) -> Connection:
    """Open (or create) a myDB database file and return a PEP 249 Connection."""
    return Connection(db_path)
