# myDB

A custom SQL database engine written in Python with a browser-based workbench UI.

---

## What it is

myDB is a from-scratch relational database engine with its own:

- **SQL parser** — Lark-based grammar covering SELECT, INSERT, UPDATE, DELETE, CREATE TABLE, DROP TABLE, ALTER TABLE
- **Storage engine** — heap file format with a buffer pool and page manager
- **Executor** — expression evaluator, WHERE/ORDER BY/LIMIT/OFFSET support
- **REST API** — FastAPI server exposing the engine over HTTP
- **Workbench** — single-file browser UI (`workbench.html`) with SQL editor, schema browser, and results grid
- **Compat layer** — DB-API 2, SQLAlchemy dialect, pandas I/O, CSV import/export

---

## Requirements

- Python 3.11+
- pip
- A modern browser (Chrome, Edge, Firefox)

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/mv-ramirez/myDB.git
cd myDB

# 2. Create and activate virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Running the server

```bash
# Start the REST API server (default port 8000)
python -m mydb.compat.rest --db demo.db

# Custom port
python -m mydb.compat.rest --db demo.db --port 8765

# Accessible from other machines
python -m mydb.compat.rest --db demo.db --host 0.0.0.0 --port 8765
```

Server output:
```
myDB REST API  →  http://127.0.0.1:8765
Database       →  demo.db
Swagger UI     →  http://127.0.0.1:8765/docs
```

---

## Loading the demo dataset

The repo includes two demo datasets — hotel and projectflow. Load them once:

```bash
# Seed both datasets into demo.db
python seed_demo.py

# Or migrate individually
python migrate_hotel.py
python migrate_projectflow.py
```

---

## Using the workbench

1. Start the server (see above)
2. Open `workbench.html` in your browser (double-click or `File > Open`)
3. The workbench auto-detects the running server (probes ports 8000–8010, 8765–8770)
4. Once connected, the schema browser populates on the left
5. Write SQL in the editor — `Ctrl+Enter` to run

### Workbench features

| Feature | Detail |
|---|---|
| Auto-connect | Detects server port on load, no manual URL entry needed |
| Schema browser | Expandable table tree with column types and PK indicators |
| SQL editor | CodeMirror with syntax highlighting and autocomplete |
| Multi-tab | `Ctrl+T` new tab, `Ctrl+W` close, double-click to rename |
| Results grid | Fixed-width columns, row numbers, type-colored values |
| Resizable panes | Drag the strip between editor and results to resize |
| Auto-expand | Results pane opens automatically when a query returns data |
| Copy CSV | Copies result set to clipboard as CSV |
| Drag to editor | Drag a table name from the sidebar into the editor |
| Format SQL | Normalises keyword casing and line breaks |
| Dark / light mode | 🌙 / ☀️ button in the top-right or `Ctrl+Shift+L` — persists to `localStorage`, falls back to OS preference |

---

## REST API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check — returns `{"status":"ok","db":"<path>"}` |
| GET | `/tables` | List all tables |
| GET | `/tables/{name}` | Table schema (columns, types, constraints) |
| GET | `/tables/{name}/rows` | Full scan with optional `?limit=&offset=` |
| POST | `/tables/{name}/rows` | Insert rows by column name |
| DELETE | `/tables/{name}` | Drop a table |
| POST | `/sql` | Execute any SQL — `{"sql":"SELECT ...","params":[]}` |
| GET | `/docs` | Swagger UI |

---

## Project structure

```
myDB/
├── workbench.html              # Single-file browser workbench
├── requirements.txt
├── demo.db.catalog.json        # Schema catalog for demo.db
├── seed_demo.py                # Loads both demo datasets
├── migrate_hotel.py            # Hotel dataset migration
├── migrate_projectflow.py      # ProjectFlow dataset migration
├── smoke_schema.py             # Quick schema smoke test
├── tests/
│   ├── test_mydb.py            # Engine unit tests
│   ├── test_rest.py            # REST API tests
│   ├── test_sqlalchemy.py      # SQLAlchemy dialect tests
│   └── test_subquery.py        # Subquery tests
└── mydb/
    ├── __init__.py
    ├── catalog/
    │   └── catalog.py          # SystemCatalog — table schema registry
    ├── sql/
    │   ├── grammar.lark        # Lark SQL grammar
    │   ├── ast_nodes.py        # AST node definitions
    │   └── parser.py           # SQL → AST
    ├── executor/
    │   ├── engine.py           # Query executor and DDL handler
    │   └── expr.py             # Expression evaluator (WHERE, ORDER BY)
    ├── storage/
    │   ├── page.py             # Fixed-size page layout
    │   ├── heap.py             # Heap file (insert, scan, update, delete)
    │   ├── buffer.py           # Buffer pool (LRU eviction)
    │   └── serializer.py       # Type-aware row serializer/deserializer
    └── compat/
        ├── rest.py             # FastAPI REST server
        ├── dbapi2.py           # PEP 249 DB-API 2 interface
        ├── sqlalchemy_dialect.py  # SQLAlchemy dialect
        ├── pandas_io.py        # read_mydb / to_mydb helpers
        ├── csv_io.py           # CSV import/export
        └── sqlite_compat.py    # sqlite3-compatible wrapper
```

---

## Running tests

```bash
pytest tests/ -v
```

---

## Connecting from Python

**DB-API 2:**
```python
from mydb.compat.dbapi2 import connect
conn = connect("demo.db")
cur  = conn.cursor()
cur.execute("SELECT * FROM hotel__guests LIMIT 5")
print(cur.fetchall())
```

**pandas:**
```python
from mydb.compat.pandas_io import read_mydb
df = read_mydb("SELECT * FROM hotel__reservations", db="demo.db")
```

**SQLAlchemy:**
```python
from sqlalchemy import create_engine, text
engine = create_engine("mydb:///demo.db")
with engine.connect() as con:
    result = con.execute(text("SELECT count(*) FROM hotel__guests"))
    print(result.fetchone())
```

---

## Demo tables

**Hotel dataset** (`hotel__*`) — 30 tables including guests, reservations, rooms, folios, employees, revenue, housekeeping, and more.

**ProjectFlow dataset** (`projectflow__*`) — workspaces, projects, sprints, issues, users, labels.

---

## Notes

- `.heap` files are binary data files (gitignored) — re-run `seed_demo.py` after cloning to populate them
- The catalog (`demo.db.catalog.json`) persists schema — heap files hold the rows
- The server reads the catalog on startup; no migration needed if the catalog file exists
