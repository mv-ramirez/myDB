"""
Pandas integration — read from and write to myDB tables via DataFrames.

Usage:
    import mydb
    from mydb.compat.pandas_io import read_table, read_sql, to_table

    conn = mydb.connect("app.db")
    df   = read_table("users", conn)
    df   = read_sql("SELECT name, age FROM users WHERE age > 25", conn)
    to_table(df, "results", conn, if_exists="replace")
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


def read_sql(sql: str, conn) -> "pd.DataFrame":
    """Execute SQL and return a DataFrame."""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required: pip install pandas")
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    cols = [d[0] for d in (cur.description or [])]
    return pd.DataFrame(rows, columns=cols)


def read_table(table: str, conn) -> "pd.DataFrame":
    return read_sql(f"SELECT * FROM {table}", conn)


def to_table(
    df: "pd.DataFrame",
    table: str,
    conn,
    if_exists: str = "fail",   # 'fail' | 'replace' | 'append'
    index: bool    = False,
):
    """Write DataFrame to a myDB table.

    if_exists:
        'fail'    — raise if table already exists
        'replace' — drop and recreate
        'append'  — insert rows into existing table
    """
    import pandas as pd
    from mydb.catalog.catalog import SystemCatalog, TableSchema, ColumnDef
    from mydb.storage.serializer import ColType

    catalog = conn._engine._catalog

    _DTYPE_MAP = {
        "int64":   ColType.BIGINT,
        "int32":   ColType.INT,
        "float64": ColType.FLOAT,
        "float32": ColType.FLOAT,
        "bool":    ColType.BOOL,
        "object":  ColType.TEXT,
        "string":  ColType.TEXT,
    }

    if if_exists == "replace":
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        except Exception:
            pass

    if if_exists in ("fail", "replace") or not catalog.table_exists(table):
        cols = []
        frame = df.reset_index() if index else df
        for col_name, dtype in frame.dtypes.items():
            col_type = _DTYPE_MAP.get(str(dtype), ColType.TEXT)
            cols.append(ColumnDef(name=str(col_name), col_type=col_type))
        schema = TableSchema(name=table, columns=cols)
        catalog.create_table(schema, if_not_exists=(if_exists == "append"))

    schema = catalog.get_table(table)
    col_names = schema.col_names()
    frame = df.reset_index() if index else df
    frame = frame[[c for c in col_names if c in frame.columns]]

    cur = conn.cursor()
    placeholders = ", ".join("?" * len(frame.columns))
    col_list     = ", ".join(frame.columns)
    sql          = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
    cur.executemany(sql, frame.itertuples(index=False, name=None))
    conn.commit()
