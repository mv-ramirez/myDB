"""
myDB — a custom SQL database engine built from scratch.

Quick start:
    import mydb

    conn = mydb.connect("myapp.db")
    cur  = conn.cursor()
    cur.execute("CREATE TABLE users (id INT, name TEXT, age INT)")
    cur.execute("INSERT INTO users (id, name, age) VALUES (?, ?, ?)", (1, "Alice", 30))
    conn.commit()
    cur.execute("SELECT * FROM users WHERE age > ?", (25,))
    print(cur.fetchall())
    conn.close()

SQLite drop-in:
    from mydb.compat.sqlite_compat import connect
    conn = connect("myapp.db")   # same API as sqlite3.connect()

Pandas:
    from mydb.compat.pandas_io import read_sql, to_table
    df = read_sql("SELECT * FROM users", conn)

CSV / JSON:
    from mydb.compat.csv_io import import_csv, export_json
    import_csv("data.csv", "users", conn)
    export_json("SELECT * FROM users", conn, "users.json")
"""

from mydb.compat.dbapi2 import (
    connect,
    Connection,
    Cursor,
    Error,
    DatabaseError,
    OperationalError,
    ProgrammingError,
    IntegrityError,
    InterfaceError,
    NotSupportedError,
    apilevel,
    threadsafety,
    paramstyle,
)

__version__ = "0.1.0"
__all__     = [
    "connect",
    "Connection",
    "Cursor",
    "Error",
    "DatabaseError",
    "OperationalError",
    "ProgrammingError",
    "IntegrityError",
    "InterfaceError",
    "NotSupportedError",
    "apilevel",
    "threadsafety",
    "paramstyle",
]
