"""Quick smoke test for schema.table syntax."""
import tempfile, os
from mydb.executor.engine import Engine
from mydb.sql.parser import parse_one

with tempfile.TemporaryDirectory() as d:
    eng = Engine(os.path.join(d, "test.db"))
    stmts = [
        "CREATE TABLE hr.employees (id INT PRIMARY KEY, name TEXT NOT NULL, salary INT)",
        "CREATE TABLE hr.departments (id INT PRIMARY KEY, name TEXT)",
        "CREATE TABLE sales.leads (id INT PRIMARY KEY, company TEXT)",
        "INSERT INTO hr.employees (id, name, salary) VALUES (1, 'Alice', 95000), (2, 'Bob', 80000)",
        "INSERT INTO hr.departments (id, name) VALUES (1, 'Engineering')",
        "INSERT INTO sales.leads (id, company) VALUES (1, 'Acme Corp')",
        "SELECT * FROM hr.employees WHERE salary > 85000",
        "SELECT COUNT(*) FROM hr.employees",
        "SELECT e.name FROM hr.employees AS e WHERE e.id IN (SELECT id FROM hr.employees WHERE salary > 85000)",
    ]
    for sql in stmts:
        r = eng.execute(parse_one(sql))
        print(f"  {sql[:55]:<55} → {r}")
    eng.close()
print("\nAll OK")
