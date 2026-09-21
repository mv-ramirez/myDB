# myDB — Rebuild Guide

Step-by-step instructions to set up myDB from scratch on a new PC or server. Follow every section in order.

---

## 1. Prerequisites

| Tool | Version | Download |
|---|---|---|
| Python | 3.11+ | https://python.org/downloads |
| Git | any | https://git-scm.com |
| Node.js | 18+ | https://nodejs.org (only if rebuilding the UI) |
| A modern browser | — | Chrome, Edge, or Firefox |

Verify installs:
```bash
python --version    # 3.11+
git --version
```

---

## 2. Clone the repository

```bash
git clone https://github.com/mv-ramirez/myDB.git
cd myDB
```

---

## 3. Create the virtual environment

```bash
python -m venv .venv
```

Activate it:

```bash
# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

---

## 4. Install dependencies

```bash
pip install -r requirements.txt
```

This installs:

| Package | Purpose |
|---|---|
| `lark>=1.2.0` | SQL grammar parser |
| `fastapi>=0.111.0` | REST API server |
| `uvicorn>=0.30.0` | ASGI server |
| `pytest>=8.0.0` | Test runner |

---

## 5. Load the demo dataset

The `.heap` data files are **not stored in the repo** (gitignored — binary format). Run the seed script to generate them from the bundled JSON definitions:

```bash
python seed_demo.py
```

This creates all `.heap` files for both the hotel and projectflow demo datasets. You should see output like:

```
Seeding hotel dataset...   ✓ 30 tables
Seeding projectflow...     ✓ 6 tables
```

To load datasets individually:

```bash
python migrate_hotel.py
python migrate_projectflow.py
```

---

## 6. Start the REST server

```bash
# Default port 8000
python -m mydb.compat.rest --db demo.db

# Custom port
python -m mydb.compat.rest --db demo.db --port 8765

# Accessible from other machines on the network
python -m mydb.compat.rest --db demo.db --host 0.0.0.0 --port 8765
```

Expected output:
```
myDB REST API  →  http://127.0.0.1:8000
Database       →  demo.db
CORS origins   →  ['*']
Swagger UI     →  http://127.0.0.1:8000/docs
```

---

## 7. Open the workbench

Double-click `workbench.html` or open it via `File > Open` in your browser.

The workbench **auto-detects** the running server — it probes ports 8000–8010 and 8765–8770 on load, finds the active instance, fills the API URL bar, and connects automatically.

If auto-detect fails, manually enter the server URL (e.g. `http://localhost:8000`) and click **Connect**.

---

## 8. Verify everything works

```bash
# Health check
curl http://localhost:8000/api/health
# → {"status":"ok","db":"demo.db"}

# List tables
curl http://localhost:8000/tables
# → {"tables":["hotel__guests","hotel__reservations",...,"projectflow__issues",...]}
```

In the workbench:
- [ ] Status dot turns green (Connected)
- [ ] Schema browser shows hotel and projectflow table groups
- [ ] Running `SELECT * FROM hotel__guests LIMIT 5` returns rows
- [ ] Results pane expands automatically

---

## 9. Run tests (optional)

```bash
pytest tests/ -v
```

All four test suites should pass:
- `test_mydb.py` — engine unit tests
- `test_rest.py` — REST API endpoint tests
- `test_sqlalchemy.py` — SQLAlchemy dialect tests
- `test_subquery.py` — subquery tests

---

## 10. Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Enter` | Run query |
| `Ctrl+Space` | Trigger SQL autocomplete |
| `Ctrl+T` | New query tab |
| `Ctrl+W` | Close current tab |
| `Ctrl+Shift+L` | Toggle dark / light mode |
| `Tab` | Indent (2 spaces) |

---

## Common issues

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: lark` | Run `pip install -r requirements.txt` with venv active |
| No `.heap` files / empty tables | Run `python seed_demo.py` |
| Workbench shows "Not connected" | Confirm server is running; manually enter URL and click Connect |
| Port already in use | Start server on a different port: `--port 8001` |
| `demo.db.catalog.json` missing | Pull latest from repo: `git pull` |
| Tests fail with import errors | Ensure you're in the project root with venv activated |

---

## Directory checklist after setup

```
myDB/
├── .venv/                      ← created in step 3
├── demo.db.catalog.json        ← schema catalog (in repo)
├── hotel__*.heap               ← created by seed_demo.py (step 5)
├── projectflow__*.heap         ← created by seed_demo.py (step 5)
├── mydb/                       ← Python engine package (in repo)
│   ├── catalog/
│   ├── compat/
│   ├── executor/
│   ├── sql/
│   └── storage/
├── tests/                      ← test suite (in repo)
├── workbench.html              ← browser UI (in repo)
├── requirements.txt
├── seed_demo.py
└── README.md
```

---

## Using myDB from Python

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
