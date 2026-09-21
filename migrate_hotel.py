"""
Migrate hotel-resort-manager-v0 → myDB (demo.db) under the `hotel` schema.

Uses direct InsertStmt AST construction (no SQL parsing per row) and
batches 200 rows per execute call for performance.

50 362 rows across 29 tables; 3 empty tables skipped.
"""
import os, sys, sqlite3, time
sys.path.insert(0, os.path.dirname(__file__))

from mydb.executor.engine import Engine
from mydb.sql.parser import parse_one
from mydb.sql.ast_nodes import InsertStmt

SRC_DB = r"C:\Users\mark.vergel.ramirez\Desktop\bench\claude\hotel-resort-manager-v0\hotel_ops.db"
DST_DB = os.path.join(os.path.dirname(__file__), "demo.db")
SCHEMA = "hotel"
BATCH  = 200          # rows per InsertStmt
MAX_TEXT = 8000       # truncate very long text fields (email bodies etc.)

# ── SQLite → myDB type ────────────────────────────────────────────────────────
def to_mydb_type(sqlite_type: str) -> str:
    t = (sqlite_type or "TEXT").upper().split("(")[0].strip()
    if t in ("INTEGER", "INT", "BIGINT", "SMALLINT", "TINYINT"):
        return "INT"
    if t in ("REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL"):
        return "FLOAT"
    if t in ("BOOLEAN", "BOOL"):
        return "BOOL"
    return "TEXT"


# ── Build CREATE TABLE DDL ────────────────────────────────────────────────────
def build_ddl(schema_name: str, cols_info: list) -> str:
    """cols_info: list of (name, sqlite_type, is_pk)"""
    parts = []
    for name, stype, is_pk in cols_info:
        mydb_type = to_mydb_type(stype)
        pk = " PRIMARY KEY" if is_pk else ""
        parts.append(f"    {name} {mydb_type}{pk}")
    return (
        f"CREATE TABLE IF NOT EXISTS {schema_name} (\n"
        + ",\n".join(parts)
        + "\n)"
    )


# ── Coerce a Python value from SQLite to myDB-safe Python ────────────────────
def coerce(val, mydb_type: str):
    if val is None:
        return None
    if mydb_type == "INT":
        try: return int(val)
        except: return None
    if mydb_type == "FLOAT":
        try: return float(val)
        except: return None
    if mydb_type == "BOOL":
        return bool(int(val)) if val is not None else None
    # TEXT — truncate very long values
    s = str(val)
    return s[:MAX_TEXT] if len(s) > MAX_TEXT else s


# ── Migrate one table ─────────────────────────────────────────────────────────
def migrate_table(src_conn, eng, src_table, dst_table, cols_info):
    col_names  = [c[0] for c in cols_info]
    col_types  = [to_mydb_type(c[1]) for c in cols_info]

    src_conn.row_factory = sqlite3.Row
    rows = src_conn.execute(f'SELECT * FROM "{src_table}"').fetchall()
    if not rows:
        print(f"  {dst_table}: 0 rows — skipped")
        return 0

    total   = 0
    errors  = 0
    batches = [rows[i:i+BATCH] for i in range(0, len(rows), BATCH)]

    for batch in batches:
        py_rows = []
        for row in batch:
            d = dict(row)
            py_rows.append([coerce(d.get(c), t) for c, t in zip(col_names, col_types)])

        stmt = InsertStmt(dst_table, col_names, py_rows)
        try:
            eng.execute(stmt)
            total += len(batch)
        except Exception as e:
            errors += len(batch)
            print(f"    ⚠  batch error in {dst_table}: {e}")

    status = f"{total}/{len(rows)} rows"
    if errors:
        status += f" ({errors} errors)"
    print(f"  {dst_table}: {status}")
    return total


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not os.path.exists(SRC_DB):
        print(f"ERROR: {SRC_DB} not found"); sys.exit(1)

    print(f"Source : {SRC_DB}")
    print(f"Target : {DST_DB}")
    print(f"Schema : {SCHEMA}.*\n")

    src  = sqlite3.connect(SRC_DB)
    eng  = Engine(DST_DB)
    t0   = time.time()

    # Get all tables with data
    all_tables = [
        r[0] for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]

    print("Creating hotel schema tables…")
    grand_total = 0

    for tbl in all_tables:
        count = src.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
        if count == 0:
            continue  # skip empty tables

        # Read column info: (name, type, is_pk)
        cols_info = [
            (r[1], r[2], bool(r[5]))
            for r in src.execute(f'PRAGMA table_info("{tbl}")').fetchall()
        ]

        dst_table = f"{SCHEMA}.{tbl}"
        ddl = build_ddl(dst_table, cols_info)
        try:
            eng.execute(parse_one(ddl))
        except Exception as e:
            print(f"  DDL error for {dst_table}: {e}")
            continue

        grand_total += migrate_table(src, eng, tbl, dst_table, cols_info)

    src.close()
    eng.close()

    elapsed = time.time() - t0
    print(f"\n✓ Migration complete — {grand_total} rows in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
