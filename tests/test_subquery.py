"""Tests for subquery support: inline views, IN/NOT IN subqueries, EXISTS, scalar subqueries."""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mydb.executor.engine import Engine


@pytest.fixture
def engine(tmp_path):
    db = str(tmp_path / "sub.db")
    eng = Engine(db)
    eng.execute(_parse(eng, "CREATE TABLE dept (id INT PRIMARY KEY, name TEXT NOT NULL)"))
    eng.execute(_parse(eng, "CREATE TABLE emp (id INT PRIMARY KEY, name TEXT NOT NULL, dept_id INT, salary INT)"))
    for stmt in [
        "INSERT INTO dept (id, name) VALUES (1, 'Engineering'), (2, 'Sales'), (3, 'HR')",
        "INSERT INTO emp (id, name, dept_id, salary) VALUES "
        "(1, 'Alice', 1, 90000), "
        "(2, 'Bob',   1, 80000), "
        "(3, 'Carol', 2, 70000), "
        "(4, 'Dave',  2, 60000), "
        "(5, 'Eve',   3, 50000)",
    ]:
        eng.execute(_parse(eng, stmt))
    yield eng
    eng.close()


def _parse(eng, sql):
    from mydb.sql.parser import parse_one
    return parse_one(sql)


def _sql(engine, sql):
    return engine.execute(_parse(engine, sql))


# ── Inline view (FROM subquery) ───────────────────────────────────────────────

def test_inline_view_basic(engine):
    rows = _sql(engine, "SELECT name FROM (SELECT name FROM emp) AS sub")
    names = {r["name"] for r in rows}
    assert names == {"Alice", "Bob", "Carol", "Dave", "Eve"}


def test_inline_view_with_where(engine):
    rows = _sql(engine, "SELECT name FROM (SELECT name, salary FROM emp) AS sub WHERE salary > 70000")
    names = {r["name"] for r in rows}
    assert names == {"Alice", "Bob"}


def test_inline_view_with_outer_filter(engine):
    rows = _sql(engine, "SELECT name, salary FROM (SELECT name, salary FROM emp WHERE dept_id = 1) AS sub")
    assert len(rows) == 2
    assert all(r["name"] in {"Alice", "Bob"} for r in rows)


def test_inline_view_aggregated_inner(engine):
    rows = _sql(engine, """
        SELECT dept_id, total
        FROM (SELECT dept_id, SUM(salary) AS total FROM emp GROUP BY dept_id) AS agg
        WHERE total > 140000
    """)
    # dept 1: 90000+80000=170000, dept 2: 70000+60000=130000 → only dept 1
    assert len(rows) == 1
    assert rows[0]["dept_id"] == 1


# ── IN (SELECT ...) ───────────────────────────────────────────────────────────

def test_in_subquery(engine):
    rows = _sql(engine, "SELECT name FROM emp WHERE dept_id IN (SELECT id FROM dept WHERE name = 'Engineering')")
    names = {r["name"] for r in rows}
    assert names == {"Alice", "Bob"}


def test_in_subquery_multiple_values(engine):
    rows = _sql(engine, "SELECT name FROM emp WHERE dept_id IN (SELECT id FROM dept WHERE name != 'HR')")
    names = {r["name"] for r in rows}
    assert names == {"Alice", "Bob", "Carol", "Dave"}


# ── NOT IN (SELECT ...) ───────────────────────────────────────────────────────

def test_not_in_subquery(engine):
    rows = _sql(engine, "SELECT name FROM emp WHERE dept_id NOT IN (SELECT id FROM dept WHERE name = 'Engineering')")
    names = {r["name"] for r in rows}
    assert names == {"Carol", "Dave", "Eve"}


# ── EXISTS ────────────────────────────────────────────────────────────────────

def test_exists_true(engine):
    rows = _sql(engine, "SELECT name FROM dept WHERE EXISTS (SELECT id FROM emp WHERE dept_id = dept.id)")
    names = {r["name"] for r in rows}
    assert names == {"Engineering", "Sales", "HR"}


def test_exists_no_match(engine):
    # dept id 99 does not exist → no emp has dept_id=99 → EXISTS is false for all
    rows = _sql(engine, "SELECT name FROM dept WHERE EXISTS (SELECT id FROM emp WHERE dept_id = 99)")
    assert rows == []


def test_not_exists(engine):
    # Add a dept with no employees
    _sql(engine, "INSERT INTO dept (id, name) VALUES (4, 'Finance')")
    rows = _sql(engine, "SELECT name FROM dept WHERE NOT EXISTS (SELECT id FROM emp WHERE dept_id = dept.id)")
    names = {r["name"] for r in rows}
    assert names == {"Finance"}


# ── Scalar subquery ───────────────────────────────────────────────────────────

def test_scalar_subquery_in_select(engine):
    rows = _sql(engine, "SELECT name, (SELECT MAX(salary) FROM emp) AS max_sal FROM emp WHERE id = 1")
    assert len(rows) == 1
    assert rows[0]["max_sal"] == 90000


def test_scalar_subquery_no_result_is_null(engine):
    rows = _sql(engine, "SELECT (SELECT id FROM emp WHERE id = 999) AS missing FROM dept WHERE id = 1")
    assert len(rows) == 1
    assert rows[0]["missing"] is None


def test_scalar_subquery_in_where(engine):
    rows = _sql(engine, "SELECT name FROM emp WHERE salary = (SELECT MAX(salary) FROM emp)")
    assert len(rows) == 1
    assert rows[0]["name"] == "Alice"


# ── Nested subqueries ─────────────────────────────────────────────────────────

def test_nested_in_subquery(engine):
    # employees in depts whose name starts with 'E'
    rows = _sql(engine, """
        SELECT name FROM emp
        WHERE dept_id IN (
            SELECT id FROM dept
            WHERE id IN (SELECT dept_id FROM emp WHERE salary > 85000)
        )
    """)
    names = {r["name"] for r in rows}
    assert names == {"Alice", "Bob"}
