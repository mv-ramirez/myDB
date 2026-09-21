"""End-to-end tests for myDB."""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mydb


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    conn = mydb.connect(path)
    conn.cursor().execute(
        "CREATE TABLE users (id INT, name TEXT, age INT, active BOOL)"
    )
    conn.commit()
    yield conn
    conn.close()


# ── Storage & serializer ───────────────────────────────────────────────────────

def test_page_insert_read():
    from mydb.storage.page import Page, PAGE_DATA
    p = Page(0, PAGE_DATA)
    data = b"hello world"
    slot = p.insert_row(data)
    assert p.get_row(slot) == data

def test_page_delete():
    from mydb.storage.page import Page, PAGE_DATA
    p = Page(0, PAGE_DATA)
    slot = p.insert_row(b"row1")
    p.delete_row(slot)
    assert p.get_row(slot) is None

def test_page_round_trip():
    from mydb.storage.page import Page, PAGE_DATA
    p = Page(42, PAGE_DATA)
    p.insert_row(b"abc")
    p2 = Page.from_bytes(p.to_bytes())
    assert p2.page_id == 42
    assert p2.get_row(0) == b"abc"

def test_serializer_int():
    from mydb.storage.serializer import encode_row, decode_row, ColType
    types = [ColType.INT, ColType.TEXT]
    vals  = [99, "hello"]
    assert decode_row(encode_row(vals, types), types) == vals

def test_serializer_nulls():
    from mydb.storage.serializer import encode_row, decode_row, ColType
    types = [ColType.INT, ColType.TEXT, ColType.FLOAT]
    vals  = [None, None, 3.14]
    result = decode_row(encode_row(vals, types), types)
    assert result[0] is None
    assert result[1] is None
    assert abs(result[2] - 3.14) < 1e-9

def test_serializer_bool():
    from mydb.storage.serializer import encode_row, decode_row, ColType
    types = [ColType.BOOL]
    assert decode_row(encode_row([True],  types), types) == [True]
    assert decode_row(encode_row([False], types), types) == [False]


# ── Parser ────────────────────────────────────────────────────────────────────

def test_parse_select():
    from mydb.sql.parser import parse_one
    from mydb.sql.ast_nodes import SelectStmt
    stmt = parse_one("SELECT * FROM users")
    assert isinstance(stmt, SelectStmt)
    assert stmt.from_.name == "users"

def test_parse_insert():
    from mydb.sql.parser import parse_one
    from mydb.sql.ast_nodes import InsertStmt
    stmt = parse_one("INSERT INTO users (id, name) VALUES (1, 'Alice')")
    assert isinstance(stmt, InsertStmt)
    assert stmt.table == "users"
    assert stmt.columns == ["id", "name"]

def test_parse_create_table():
    from mydb.sql.parser import parse_one
    from mydb.sql.ast_nodes import CreateTableStmt
    stmt = parse_one("CREATE TABLE t (id INT, name TEXT)")
    assert isinstance(stmt, CreateTableStmt)
    assert stmt.table == "t"
    assert len(stmt.columns) == 2

def test_parse_where():
    from mydb.sql.parser import parse_one
    from mydb.sql.ast_nodes import SelectStmt, BinOp
    stmt = parse_one("SELECT * FROM users WHERE age > 18")
    assert isinstance(stmt.where, BinOp)
    assert stmt.where.op == ">"


# ── Catalog ───────────────────────────────────────────────────────────────────

def test_catalog_create_list(tmp_path):
    from mydb.catalog.catalog import SystemCatalog, TableSchema, ColumnDef
    from mydb.storage.serializer import ColType
    path = str(tmp_path / "test.db")
    cat  = SystemCatalog(path)
    schema = TableSchema("orders", [ColumnDef("id", ColType.INT)])
    cat.create_table(schema)
    assert "orders" in [t.lower() for t in cat.list_tables()]

def test_catalog_drop(tmp_path):
    from mydb.catalog.catalog import SystemCatalog, TableSchema, ColumnDef
    from mydb.storage.serializer import ColType
    path = str(tmp_path / "test.db")
    cat  = SystemCatalog(path)
    cat.create_table(TableSchema("tmp", [ColumnDef("x", ColType.INT)]))
    cat.drop_table("tmp")
    assert not cat.table_exists("tmp")

def test_catalog_duplicate_raises(tmp_path):
    from mydb.catalog.catalog import SystemCatalog, TableSchema, ColumnDef
    from mydb.storage.serializer import ColType
    path = str(tmp_path / "test.db")
    cat  = SystemCatalog(path)
    cat.create_table(TableSchema("dup", [ColumnDef("x", ColType.INT)]))
    with pytest.raises(ValueError):
        cat.create_table(TableSchema("dup", [ColumnDef("x", ColType.INT)]))


# ── End-to-end SQL execution ──────────────────────────────────────────────────

def test_insert_and_select(db):
    cur = db.cursor()
    cur.execute("INSERT INTO users (id, name, age) VALUES (?, ?, ?)", (1, "Alice", 30))
    cur.execute("INSERT INTO users (id, name, age) VALUES (?, ?, ?)", (2, "Bob", 25))
    db.commit()
    cur.execute("SELECT * FROM users")
    rows = cur.fetchall()
    assert len(rows) == 2

def test_where_filter(db):
    cur = db.cursor()
    cur.execute("INSERT INTO users (id, name, age) VALUES (1, 'Alice', 30)")
    cur.execute("INSERT INTO users (id, name, age) VALUES (2, 'Bob', 20)")
    db.commit()
    cur.execute("SELECT * FROM users WHERE age > 25")
    rows = cur.fetchall()
    assert len(rows) == 1

def test_update(db):
    cur = db.cursor()
    cur.execute("INSERT INTO users (id, name, age) VALUES (1, 'Alice', 30)")
    db.commit()
    cur.execute("UPDATE users SET age = 31 WHERE id = 1")
    db.commit()
    cur.execute("SELECT age FROM users WHERE id = 1")
    row = cur.fetchone()
    assert row[0] == 31

def test_delete(db):
    cur = db.cursor()
    cur.execute("INSERT INTO users (id, name, age) VALUES (1, 'Alice', 30)")
    cur.execute("INSERT INTO users (id, name, age) VALUES (2, 'Bob', 25)")
    db.commit()
    cur.execute("DELETE FROM users WHERE id = 2")
    db.commit()
    cur.execute("SELECT * FROM users")
    assert len(cur.fetchall()) == 1

def test_order_by(db):
    cur = db.cursor()
    cur.execute("INSERT INTO users (id, name, age) VALUES (1, 'Alice', 30)")
    cur.execute("INSERT INTO users (id, name, age) VALUES (2, 'Bob', 20)")
    cur.execute("INSERT INTO users (id, name, age) VALUES (3, 'Carol', 25)")
    db.commit()
    cur.execute("SELECT name FROM users ORDER BY age ASC")
    names = [r[0] for r in cur.fetchall()]
    assert names == ["Bob", "Carol", "Alice"]

def test_limit_offset(db):
    cur = db.cursor()
    for i in range(5):
        cur.execute(f"INSERT INTO users (id, name, age) VALUES ({i}, 'u{i}', {20+i})")
    db.commit()
    cur.execute("SELECT * FROM users LIMIT 2 OFFSET 1")
    assert len(cur.fetchall()) == 2

def test_count_aggregate(db):
    cur = db.cursor()
    cur.execute("INSERT INTO users (id, name, age) VALUES (1, 'Alice', 30)")
    cur.execute("INSERT INTO users (id, name, age) VALUES (2, 'Bob', 25)")
    db.commit()
    cur.execute("SELECT COUNT(*) FROM users")
    row = cur.fetchone()
    assert row[0] == 2

def test_like(db):
    cur = db.cursor()
    cur.execute("INSERT INTO users (id, name, age) VALUES (1, 'Alice', 30)")
    cur.execute("INSERT INTO users (id, name, age) VALUES (2, 'Bob', 25)")
    db.commit()
    cur.execute("SELECT * FROM users WHERE name LIKE 'Al%'")
    assert len(cur.fetchall()) == 1

def test_drop_table(db):
    cur = db.cursor()
    cur.execute("CREATE TABLE tmp (x INT)")
    cur.execute("DROP TABLE tmp")
    with pytest.raises(Exception):
        cur.execute("SELECT * FROM tmp")

def test_executemany(db):
    cur = db.cursor()
    data = [(i, f"user{i}", 20 + i) for i in range(10)]
    cur.executemany("INSERT INTO users (id, name, age) VALUES (?, ?, ?)", data)
    db.commit()
    cur.execute("SELECT COUNT(*) FROM users")
    assert cur.fetchone()[0] == 10

def test_fetchone_fetchmany(db):
    cur = db.cursor()
    cur.execute("INSERT INTO users (id, name, age) VALUES (1, 'A', 20)")
    cur.execute("INSERT INTO users (id, name, age) VALUES (2, 'B', 21)")
    db.commit()
    cur.execute("SELECT * FROM users")
    r1 = cur.fetchone()
    assert r1 is not None
    rest = cur.fetchmany(5)
    assert len(rest) == 1

def test_persistence(tmp_path):
    path = str(tmp_path / "persist.db")
    conn = mydb.connect(path)
    conn.cursor().execute("CREATE TABLE t (x INT)")
    conn.cursor().execute("INSERT INTO t (x) VALUES (42)")
    conn.commit()
    conn.close()

    conn2 = mydb.connect(path)
    cur   = conn2.cursor()
    cur.execute("SELECT * FROM t")
    rows = cur.fetchall()
    conn2.close()
    assert rows == [(42,)]


# ── SQLite compat ─────────────────────────────────────────────────────────────

def test_sqlite_compat(tmp_path):
    from mydb.compat.sqlite_compat import connect
    path = str(tmp_path / "compat.db")
    conn = connect(path)
    conn.execute("CREATE TABLE items (id INT, label TEXT)")
    conn.execute("INSERT INTO items (id, label) VALUES (1, 'alpha')")
    conn.commit()
    rows = conn.execute("SELECT * FROM items").fetchall()
    assert rows == [(1, "alpha")]
    conn.close()
