"""REST API layer tests — uses FastAPI TestClient (httpx transport)."""
import os
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mydb.compat.rest import make_app


@pytest.fixture
def client(tmp_path):
    db = str(tmp_path / "rest_test.db")
    app = make_app(db)
    with TestClient(app) as c:
        # seed schema
        c.post("/sql", json={"sql": "CREATE TABLE items (id INT, name TEXT, price FLOAT)"})
        yield c


# ── Health ───────────────────────────────────────────────────────────────────

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── SQL endpoint ──────────────────────────────────────────────────────────────

def test_sql_create_and_list(client):
    r = client.post("/sql", json={"sql": "CREATE TABLE orders (oid INT, total FLOAT)"})
    assert r.status_code == 200
    tables = client.get("/tables").json()["tables"]
    assert "orders" in tables

def test_sql_insert_and_select(client):
    client.post("/sql", json={"sql": "INSERT INTO items (id, name, price) VALUES (1, 'Pen', 1.5)"})
    r = client.post("/sql", json={"sql": "SELECT * FROM items"})
    assert r.status_code == 200
    body = r.json()
    assert body["columns"] == ["id", "name", "price"]
    assert body["rows"] == [[1, "Pen", 1.5]]

def test_sql_with_params(client):
    client.post("/sql", json={"sql": "INSERT INTO items (id, name, price) VALUES (?, ?, ?)",
                              "params": [2, "Ruler", 0.99]})
    r = client.post("/sql", json={"sql": "SELECT name FROM items WHERE id = ?", "params": [2]})
    assert r.json()["rows"] == [["Ruler"]]

def test_sql_where(client):
    client.post("/sql", json={"sql": "INSERT INTO items (id, name, price) VALUES (1, 'A', 5.0)"})
    client.post("/sql", json={"sql": "INSERT INTO items (id, name, price) VALUES (2, 'B', 15.0)"})
    r = client.post("/sql", json={"sql": "SELECT id FROM items WHERE price > 10"})
    assert r.json()["rows"] == [[2]]

def test_sql_update(client):
    client.post("/sql", json={"sql": "INSERT INTO items (id, name, price) VALUES (1, 'X', 1.0)"})
    client.post("/sql", json={"sql": "UPDATE items SET price = 9.99 WHERE id = 1"})
    r = client.post("/sql", json={"sql": "SELECT price FROM items WHERE id = 1"})
    assert abs(r.json()["rows"][0][0] - 9.99) < 1e-6

def test_sql_delete(client):
    client.post("/sql", json={"sql": "INSERT INTO items (id, name, price) VALUES (1, 'Del', 0.0)"})
    client.post("/sql", json={"sql": "DELETE FROM items WHERE id = 1"})
    r = client.post("/sql", json={"sql": "SELECT * FROM items"})
    assert r.json()["rows"] == []

def test_sql_count(client):
    for i in range(3):
        client.post("/sql", json={"sql": f"INSERT INTO items (id, name, price) VALUES ({i}, 'x', 1.0)"})
    r = client.post("/sql", json={"sql": "SELECT COUNT(*) FROM items"})
    assert r.json()["rows"] == [[3]]

def test_sql_bad_table(client):
    r = client.post("/sql", json={"sql": "SELECT * FROM nonexistent"})
    assert r.status_code == 400


# ── Catalog endpoints ─────────────────────────────────────────────────────────

def test_list_tables(client):
    r = client.get("/tables")
    assert r.status_code == 200
    assert "items" in r.json()["tables"]

def test_get_table_schema(client):
    r = client.get("/tables/items")
    assert r.status_code == 200
    body = r.json()
    assert body["table"] == "items"
    col_names = [c["name"] for c in body["columns"]]
    assert col_names == ["id", "name", "price"]

def test_get_table_not_found(client):
    r = client.get("/tables/ghost")
    assert r.status_code == 404


# ── Row endpoints ─────────────────────────────────────────────────────────────

def test_scan_rows(client):
    client.post("/sql", json={"sql": "INSERT INTO items (id, name, price) VALUES (1, 'A', 1.0)"})
    r = client.get("/tables/items/rows")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == [[1, "A", 1.0]]

def test_scan_rows_limit_offset(client):
    for i in range(5):
        client.post("/sql", json={"sql": f"INSERT INTO items (id, name, price) VALUES ({i}, 'x', {float(i)})"})
    r = client.get("/tables/items/rows?limit=2&offset=1")
    assert r.status_code == 200
    assert len(r.json()["rows"]) == 2

def test_insert_rows_endpoint(client):
    r = client.post("/tables/items/rows", json={
        "columns": ["id", "name", "price"],
        "rows":    [[10, "Marker", 2.5], [11, "Eraser", 0.75]],
    })
    assert r.status_code == 200
    assert r.json()["rows_affected"] == 2
    check = client.post("/sql", json={"sql": "SELECT COUNT(*) FROM items"})
    assert check.json()["rows"] == [[2]]

def test_insert_rows_bad_table(client):
    r = client.post("/tables/ghost/rows", json={"columns": ["x"], "rows": [[1]]})
    assert r.status_code == 404


# ── Drop table endpoint ───────────────────────────────────────────────────────

def test_drop_table_endpoint(client):
    client.post("/sql", json={"sql": "CREATE TABLE temp_tbl (x INT)"})
    r = client.delete("/tables/temp_tbl")
    assert r.status_code == 200
    assert client.get("/tables/temp_tbl").status_code == 404

def test_drop_table_not_found(client):
    r = client.delete("/tables/ghost")
    assert r.status_code == 404
