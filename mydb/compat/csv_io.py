"""
CSV / JSON import-export for myDB.

Usage:
    from mydb.compat.csv_io import import_csv, export_csv, import_json, export_json
    import mydb

    conn = mydb.connect("app.db")
    import_csv("users.csv", "users", conn)           # CSV → table
    export_csv("SELECT * FROM users", conn, "out.csv")
    import_json("orders.json", "orders", conn)       # JSON array → table
    export_json("SELECT * FROM orders", conn, "orders_out.json")
"""
import csv
import json
from mydb.catalog.catalog import SystemCatalog, TableSchema, ColumnDef
from mydb.storage.serializer import ColType


def import_csv(file_path: str, table: str, conn, has_header: bool = True, if_exists: str = "append"):
    """Read a CSV file and insert rows into `table`.

    if_exists: 'append' (default) | 'replace'
    """
    with open(file_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows   = list(reader)

    if not rows:
        return

    headers = rows[0] if has_header else [f"col{i}" for i in range(len(rows[0]))]
    data    = rows[1:] if has_header else rows

    catalog = conn._engine._catalog
    if not catalog.table_exists(table):
        cols = [ColumnDef(name=h, col_type=ColType.TEXT) for h in headers]
        catalog.create_table(TableSchema(name=table, columns=cols))
    elif if_exists == "replace":
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        cols = [ColumnDef(name=h, col_type=ColType.TEXT) for h in headers]
        catalog.create_table(TableSchema(name=table, columns=cols))

    col_list     = ", ".join(headers)
    placeholders = ", ".join("?" * len(headers))
    sql          = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
    cur          = conn.cursor()
    for row in data:
        cur.execute(sql, row)
    conn.commit()


def export_csv(sql: str, conn, file_path: str):
    """Execute SQL and write results to a CSV file."""
    cur = conn.cursor()
    cur.execute(sql)
    headers = [d[0] for d in (cur.description or [])]
    rows    = cur.fetchall()
    with open(file_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def import_json(file_path: str, table: str, conn, if_exists: str = "append"):
    """Read a JSON array file and insert rows into `table`."""
    with open(file_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    if not records:
        return

    headers = list(records[0].keys())
    catalog = conn._engine._catalog
    if not catalog.table_exists(table):
        cols = [ColumnDef(name=h, col_type=ColType.TEXT) for h in headers]
        catalog.create_table(TableSchema(name=table, columns=cols))
    elif if_exists == "replace":
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        cols = [ColumnDef(name=h, col_type=ColType.TEXT) for h in headers]
        catalog.create_table(TableSchema(name=table, columns=cols))

    col_list     = ", ".join(headers)
    placeholders = ", ".join("?" * len(headers))
    sql          = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
    cur          = conn.cursor()
    for record in records:
        cur.execute(sql, [record.get(h) for h in headers])
    conn.commit()


def export_json(sql: str, conn, file_path: str):
    """Execute SQL and write results to a JSON array file."""
    cur = conn.cursor()
    cur.execute(sql)
    headers = [d[0] for d in (cur.description or [])]
    rows    = cur.fetchall()
    data    = [dict(zip(headers, row)) for row in rows]
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
