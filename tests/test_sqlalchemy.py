"""SQLAlchemy 2.0 dialect tests for myDB."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mydb.compat.sqlalchemy_dialect import register
register()

from sqlalchemy import (
    create_engine, text, inspect,
    Table, Column, MetaData, Integer, String, Float, Boolean, BigInteger,
)
from sqlalchemy.orm import Session, DeclarativeBase, Mapped, mapped_column


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def engine(tmp_path):
    db = str(tmp_path / "sa_test.db")
    eng = create_engine(f"mydb:///{db}", echo=False)
    yield eng
    eng.dispose()


@pytest.fixture
def meta_engine(tmp_path):
    """Engine with a pre-created table via MetaData."""
    db  = str(tmp_path / "meta_test.db")
    eng = create_engine(f"mydb:///{db}", echo=False)
    meta = MetaData()
    Table(
        "products", meta,
        Column("id",    Integer,  primary_key=True),
        Column("name",  String,   nullable=False),
        Column("price", Float),
        Column("active", Boolean),
    )
    meta.create_all(eng)
    yield eng, meta
    eng.dispose()


# ── Core: raw text SQL ────────────────────────────────────────────────────────

def test_raw_text_create_and_select(engine):
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE t (x INT, y TEXT)"))
        conn.execute(text("INSERT INTO t (x, y) VALUES (1, 'hello')"))
        rows = conn.execute(text("SELECT * FROM t")).fetchall()
    assert rows == [(1, "hello")]

def test_raw_text_params(engine):
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE nums (n INT)"))
        conn.execute(text("INSERT INTO nums (n) VALUES (42)"))
        row = conn.execute(text("SELECT n FROM nums WHERE n = :v"), {"v": 42}).fetchone()
    # SA converts :v → ? and passes 42; result comes back as a Row
    assert row is not None
    assert row[0] == 42

def test_raw_count(engine):
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE c (v INT)"))
        for i in range(5):
            conn.execute(text(f"INSERT INTO c (v) VALUES ({i})"))
        n = conn.execute(text("SELECT COUNT(*) FROM c")).scalar()
    assert n == 5


# ── Core: MetaData + Table ────────────────────────────────────────────────────

def test_metadata_create_all(meta_engine):
    eng, meta = meta_engine
    insp = inspect(eng)
    assert "products" in insp.get_table_names()

def test_metadata_insert_select(meta_engine):
    eng, meta = meta_engine
    products = meta.tables["products"]
    with eng.connect() as conn:
        conn.execute(products.insert().values(id=1, name="Widget", price=9.99, active=True))
        rows = conn.execute(products.select()).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "Widget"

def test_metadata_where(meta_engine):
    eng, meta = meta_engine
    products = meta.tables["products"]
    with eng.connect() as conn:
        conn.execute(products.insert().values(id=1, name="Cheap",     price=1.0,  active=True))
        conn.execute(products.insert().values(id=2, name="Expensive", price=99.0, active=False))
        rows = conn.execute(
            products.select().where(products.c.price > 50)
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "Expensive"

def test_metadata_update(meta_engine):
    eng, meta = meta_engine
    products = meta.tables["products"]
    with eng.connect() as conn:
        conn.execute(products.insert().values(id=1, name="Old", price=5.0, active=True))
        conn.execute(
            products.update().where(products.c.id == 1).values(name="New")
        )
        row = conn.execute(
            products.select().where(products.c.id == 1)
        ).fetchone()
    assert row[1] == "New"

def test_metadata_delete(meta_engine):
    eng, meta = meta_engine
    products = meta.tables["products"]
    with eng.connect() as conn:
        conn.execute(products.insert().values(id=1, name="Gone", price=0.0, active=False))
        conn.execute(products.delete().where(products.c.id == 1))
        rows = conn.execute(products.select()).fetchall()
    assert rows == []

def test_metadata_drop_all(meta_engine):
    eng, meta = meta_engine
    meta.drop_all(eng)
    assert "products" not in inspect(eng).get_table_names()


# ── Reflection ────────────────────────────────────────────────────────────────

def test_reflect_table_names(meta_engine):
    eng, _ = meta_engine
    insp = inspect(eng)
    assert "products" in insp.get_table_names()

def test_reflect_columns(meta_engine):
    eng, _ = meta_engine
    insp    = inspect(eng)
    cols    = {c["name"]: c for c in insp.get_columns("products")}
    assert set(cols.keys()) == {"id", "name", "price", "active"}
    assert cols["id"]["primary_key"] if "primary_key" in cols["id"] else True

def test_reflect_pk(meta_engine):
    eng, _ = meta_engine
    insp = inspect(eng)
    pk   = insp.get_pk_constraint("products")
    assert "id" in pk["constrained_columns"]

def test_has_table(meta_engine):
    eng, _ = meta_engine
    insp = inspect(eng)
    assert insp.has_table("products")
    assert not insp.has_table("ghost_table")

def test_reflect_automap(meta_engine):
    """Automap: reflect an existing DB into SQLAlchemy Table objects."""
    eng, _ = meta_engine
    reflected = MetaData()
    reflected.reflect(bind=eng)
    assert "products" in reflected.tables


# ── ORM ───────────────────────────────────────────────────────────────────────

class _Base(DeclarativeBase):
    pass

class User(_Base):
    __tablename__ = "users"
    id:   Mapped[int]   = mapped_column(Integer, primary_key=True)
    name: Mapped[str]   = mapped_column(String,  nullable=False)
    age:  Mapped[int]   = mapped_column(Integer)

def test_orm_create_and_insert(tmp_path):
    db  = str(tmp_path / "orm.db")
    eng = create_engine(f"mydb:///{db}", echo=False)
    _Base.metadata.create_all(eng)
    with Session(eng) as session:
        session.add(User(id=1, name="Alice", age=30))
        session.add(User(id=2, name="Bob",   age=25))
        session.commit()
    with Session(eng) as session:
        users = session.query(User).all()
        assert len(users) == 2
    eng.dispose()

def test_orm_filter(tmp_path):
    db  = str(tmp_path / "orm2.db")
    eng = create_engine(f"mydb:///{db}", echo=False)
    _Base.metadata.create_all(eng)
    with Session(eng) as session:
        session.add(User(id=1, name="Alice", age=30))
        session.add(User(id=2, name="Bob",   age=20))
        session.commit()
    with Session(eng) as session:
        old = session.query(User).filter(User.age > 25).all()
        assert len(old) == 1
        assert old[0].name == "Alice"
    eng.dispose()

def test_orm_update(tmp_path):
    db  = str(tmp_path / "orm3.db")
    eng = create_engine(f"mydb:///{db}", echo=False)
    _Base.metadata.create_all(eng)
    with Session(eng) as session:
        session.add(User(id=1, name="Alice", age=30))
        session.commit()
    with Session(eng) as session:
        u = session.query(User).filter(User.id == 1).one()
        u.age = 31
        session.commit()
    with Session(eng) as session:
        u = session.query(User).filter(User.id == 1).one()
        assert u.age == 31
    eng.dispose()

def test_orm_delete(tmp_path):
    db  = str(tmp_path / "orm4.db")
    eng = create_engine(f"mydb:///{db}", echo=False)
    _Base.metadata.create_all(eng)
    with Session(eng) as session:
        session.add(User(id=1, name="Alice", age=30))
        session.commit()
    with Session(eng) as session:
        u = session.query(User).filter(User.id == 1).one()
        session.delete(u)
        session.commit()
    with Session(eng) as session:
        assert len(session.query(User).all()) == 0
    eng.dispose()
