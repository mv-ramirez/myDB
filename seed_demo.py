"""Seed demo.db with schema-qualified tables to showcase sidebar grouping."""
import os, glob
from mydb.executor.engine import Engine
from mydb.sql.parser import parse_one

# wipe existing db files
for f in glob.glob("demo.db*") + glob.glob("*.heap"):
    try:
        os.remove(f)
    except OSError:
        pass

eng = Engine("demo.db")

stmts = [
    # ── hr schema ──────────────────────────────────────────────────────────────
    """CREATE TABLE hr.departments (
        id     INT PRIMARY KEY,
        name   TEXT NOT NULL,
        budget INT
    )""",
    """CREATE TABLE hr.employees (
        id        INT PRIMARY KEY,
        name      TEXT NOT NULL,
        dept_id   INT,
        role      TEXT,
        salary    INT,
        active    BOOL
    )""",
    """CREATE TABLE hr.job_grades (
        grade   INT PRIMARY KEY,
        title   TEXT NOT NULL,
        min_sal INT,
        max_sal INT
    )""",

    # ── sales schema ───────────────────────────────────────────────────────────
    """CREATE TABLE sales.leads (
        id       INT PRIMARY KEY,
        company  TEXT NOT NULL,
        owner_id INT,
        stage    TEXT,
        value    INT
    )""",
    """CREATE TABLE sales.pipeline (
        id      INT PRIMARY KEY,
        lead_id INT,
        status  TEXT,
        closed  BOOL
    )""",

    # ── finance schema ─────────────────────────────────────────────────────────
    """CREATE TABLE finance.budgets (
        id      INT PRIMARY KEY,
        dept_id INT,
        year    INT,
        amount  INT
    )""",
    """CREATE TABLE finance.expenses (
        id       INT PRIMARY KEY,
        dept_id  INT,
        category TEXT,
        amount   INT,
        approved BOOL
    )""",

    # ── flat (no schema) ───────────────────────────────────────────────────────
    """CREATE TABLE config (
        key   TEXT PRIMARY KEY,
        value TEXT
    )""",

    # ── data ───────────────────────────────────────────────────────────────────
    "INSERT INTO hr.departments (id, name, budget) VALUES "
    "(1, 'Engineering', 500000), (2, 'Sales', 300000), (3, 'HR', 150000), (4, 'Finance', 200000)",

    "INSERT INTO hr.employees (id, name, dept_id, role, salary, active) VALUES "
    "(1, 'Alice',  1, 'Engineer',   95000, TRUE), "
    "(2, 'Bob',    1, 'Engineer',   88000, TRUE), "
    "(3, 'Carol',  2, 'Account Exec', 72000, TRUE), "
    "(4, 'Dave',   2, 'SDR',        58000, FALSE), "
    "(5, 'Eve',    3, 'HR Manager', 80000, TRUE), "
    "(6, 'Frank',  1, 'Tech Lead',  115000, TRUE), "
    "(7, 'Grace',  4, 'CFO',        145000, TRUE), "
    "(8, 'Henry',  1, 'Engineer',   78000, FALSE)",

    "INSERT INTO hr.job_grades (grade, title, min_sal, max_sal) VALUES "
    "(1, 'Junior', 50000, 75000), "
    "(2, 'Mid',    75000, 100000), "
    "(3, 'Senior', 100000, 140000), "
    "(4, 'Staff',  140000, 200000)",

    "INSERT INTO sales.leads (id, company, owner_id, stage, value) VALUES "
    "(1, 'Acme Corp',    3, 'Proposal',   120000), "
    "(2, 'Globex',       3, 'Discovery',   45000), "
    "(3, 'Initech',      4, 'Negotiation', 80000), "
    "(4, 'Umbrella',     4, 'Closed Won', 200000)",

    "INSERT INTO sales.pipeline (id, lead_id, status, closed) VALUES "
    "(1, 1, 'Active',      FALSE), "
    "(2, 2, 'Active',      FALSE), "
    "(3, 3, 'Active',      FALSE), "
    "(4, 4, 'Won',         TRUE)",

    "INSERT INTO finance.budgets (id, dept_id, year, amount) VALUES "
    "(1, 1, 2026, 500000), (2, 2, 2026, 300000), "
    "(3, 3, 2026, 150000), (4, 4, 2026, 200000)",

    "INSERT INTO finance.expenses (id, dept_id, category, amount, approved) VALUES "
    "(1, 1, 'Software',  12000, TRUE), "
    "(2, 1, 'Hardware',  45000, TRUE), "
    "(3, 2, 'Travel',     8000, TRUE), "
    "(4, 3, 'Training',   3000, FALSE), "
    "(5, 4, 'Consulting', 20000, TRUE)",

    "INSERT INTO config (key, value) VALUES "
    "('app_version', '1.0.0'), ('max_connections', '100'), ('timezone', 'UTC')",
]

for sql in stmts:
    eng.execute(parse_one(sql))

eng.close()

tables = ["hr.departments", "hr.employees", "hr.job_grades",
          "sales.leads", "sales.pipeline",
          "finance.budgets", "finance.expenses",
          "config"]
print(f"demo.db seeded — {len(tables)} tables across 3 schemas + 1 flat table")
for t in tables:
    print(f"  {t}")
