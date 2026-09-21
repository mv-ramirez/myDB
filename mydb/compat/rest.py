"""
myDB REST/HTTP API layer.

Exposes a myDB database over HTTP using FastAPI.

Start with:
    python -m mydb.compat.rest --db myapp.db [--host 0.0.0.0] [--port 8000]

Or mount as a sub-app in an existing FastAPI application:
    from mydb.compat.rest import make_app
    app = make_app("myapp.db")

Endpoints
---------
POST /sql
    Execute any SQL statement.
    Body:  {"sql": "SELECT ...", "params": []}
    200:   {"columns": [...], "rows": [[...]], "rows_affected": null}

GET  /tables
    List all tables in the database.
    200:   {"tables": ["users", "orders", ...]}

GET  /tables/{name}
    Return a table's schema.
    200:   {"table": "users", "columns": [{"name": "id", "type": "INT", ...}]}

GET  /tables/{name}/rows
    Full table scan with optional LIMIT / OFFSET.
    Query params: limit (int), offset (int)
    200:   {"table": "users", "columns": [...], "rows": [[...]]}

POST /tables/{name}/rows
    Insert one or more rows using column names.
    Body:  {"columns": ["id", "name"], "rows": [[1, "Alice"], [2, "Bob"]]}
    200:   {"rows_affected": 2}

DELETE /tables/{name}
    Drop a table.
    200:   {"result": "dropped"}

GET  /health
    Liveness probe.
    200:   {"status": "ok", "db": "<path>"}
"""
from __future__ import annotations

import traceback
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mydb.executor.engine import Engine
from mydb.catalog.catalog import SystemCatalog
from mydb.compat.dbapi2 import Cursor as _Cursor, _quote
from mydb.sql.parser import parse_one
from mydb.sql.ast_nodes import SelectStmt


# ── Request / response models ─────────────────────────────────────────────────

class SqlRequest(BaseModel):
    sql: str
    params: list[Any] | None = None


class InsertRequest(BaseModel):
    columns: list[str]
    rows: list[list[Any]]


# ── App factory ───────────────────────────────────────────────────────────────

def make_app(db_path: str, cors_origins: list[str] | None = None) -> FastAPI:
    """Create and return a FastAPI application bound to *db_path*.

    *cors_origins* is the list of allowed origins passed to CORSMiddleware.
    Pass ``["*"]`` to allow all origins (useful when the workbench is opened
    from a local file or a different port).  Defaults to ``["*"]``.
    """

    engine: Engine | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal engine
        engine = Engine(db_path)
        yield
        if engine:
            engine.close()

    app = FastAPI(
        title="myDB REST API",
        description="HTTP interface for the myDB custom SQL engine",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins if cors_origins is not None else ["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        allow_credentials=False,
    )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _engine() -> Engine:
        if engine is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        return engine

    def _run_sql(sql: str, params: list | None = None) -> JSONResponse:
        sql = sql.strip()
        if params:
            sql = _Cursor._bind(sql, params)
        try:
            stmt   = parse_one(sql)
            result = _engine().execute(stmt)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")

        is_select = isinstance(stmt, SelectStmt)
        if is_select and result:
            columns = list(result[0].keys())
            rows    = [list(r.values()) for r in result]
            return JSONResponse({"columns": columns, "rows": rows, "rows_affected": None})
        if is_select:
            return JSONResponse({"columns": [], "rows": [], "rows_affected": None})
        # DML / DDL
        meta = result[0] if result else {}
        return JSONResponse({
            "columns":      None,
            "rows":         None,
            "rows_affected": meta.get("rows_affected"),
            "result":       meta.get("result"),
        })

    # ── routes ────────────────────────────────────────────────────────────────

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok", "db": db_path}

    @app.post("/sql", tags=["sql"])
    def execute_sql(req: SqlRequest):
        """Execute any SQL statement and return results."""
        return _run_sql(req.sql, req.params)

    @app.get("/tables", tags=["catalog"])
    def list_tables():
        """List all tables in the database."""
        tables = _engine()._catalog.list_tables()
        return {"tables": sorted(tables)}

    @app.get("/tables/{name}", tags=["catalog"])
    def get_table(name: str):
        """Return schema for a single table."""
        schema = _engine()._catalog.get_table(name.lower())
        if schema is None:
            raise HTTPException(status_code=404, detail=f"Table '{name}' not found")
        columns = [
            {
                "name":        c.name,
                "type":        c.col_type.name,
                "nullable":    c.nullable,
                "primary_key": c.primary_key,
                "unique":      c.unique,
                "default":     c.default,
            }
            for c in schema.columns
        ]
        return {"table": schema.name, "columns": columns}

    @app.get("/tables/{name}/rows", tags=["data"])
    def scan_table(
        name: str,
        limit:  int | None = Query(default=None, ge=1),
        offset: int        = Query(default=0,    ge=0),
    ):
        """Scan rows from a table with optional LIMIT and OFFSET."""
        schema = _engine()._catalog.get_table(name.lower())
        if schema is None:
            raise HTTPException(status_code=404, detail=f"Table '{name}' not found")
        sql = f"SELECT * FROM {name}"
        if limit is not None:
            sql += f" LIMIT {limit} OFFSET {offset}"
        elif offset:
            sql += f" LIMIT 9999999 OFFSET {offset}"
        return _run_sql(sql)

    @app.post("/tables/{name}/rows", tags=["data"])
    def insert_rows(name: str, req: InsertRequest):
        """Insert one or more rows into a table."""
        schema = _engine()._catalog.get_table(name.lower())
        if schema is None:
            raise HTTPException(status_code=404, detail=f"Table '{name}' not found")
        if not req.rows:
            return {"rows_affected": 0}

        col_list = ", ".join(req.columns)
        count    = 0
        eng      = _engine()
        try:
            for row_vals in req.rows:
                placeholders = ", ".join(_quote(v) for v in row_vals)
                sql = f"INSERT INTO {name} ({col_list}) VALUES ({placeholders})"
                stmt = parse_one(sql)
                eng.execute(stmt)
                count += 1
            eng._heaps[name.lower()].flush()
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
        return {"rows_affected": count}

    @app.delete("/tables/{name}", tags=["catalog"])
    def drop_table(name: str):
        """Drop a table from the database."""
        schema = _engine()._catalog.get_table(name.lower())
        if schema is None:
            raise HTTPException(status_code=404, detail=f"Table '{name}' not found")
        return _run_sql(f"DROP TABLE {name}")

    return app


# ── CLI entry point ───────────────────────────────────────────────────────────

def _main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="myDB REST server")
    parser.add_argument("--db",   default="mydb.db", help="Path to the .db file")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--reload", action="store_true", help="Hot-reload (dev only)")
    parser.add_argument(
        "--cors-origins", nargs="*", default=None, metavar="ORIGIN",
        help="Allowed CORS origins (default: *). Example: --cors-origins https://myapp.com",
    )
    args = parser.parse_args()

    cors = args.cors_origins  # None → make_app defaults to ["*"]
    print(f"myDB REST API  →  http://{args.host}:{args.port}")
    print(f"Database       →  {args.db}")
    print(f"CORS origins   →  {cors or ['*']}")
    print(f"Swagger UI     →  http://{args.host}:{args.port}/docs")

    app = make_app(args.db, cors_origins=cors)
    uvicorn.run(app, host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    _main()
