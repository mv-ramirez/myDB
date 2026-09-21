"""
Migrate project-flow SQLite data → myDB (demo.db) under the `projectflow` schema.

Tables migrated:
  projectflow.workspaces   (1 row)
  projectflow.projects     (1 row)
  projectflow.issues       (9 rows)
  projectflow.sprints      (3 rows)
  projectflow.users        (7 rows)
  projectflow.labels       (18 rows)

JSON / array fields are stored as TEXT (JSON strings).
"""
import json
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from mydb.executor.engine import Engine
from mydb.sql.parser import parse_one

# ── Source ────────────────────────────────────────────────────────────────────
SRC_DB = r"C:\Users\mark.vergel.ramirez\Desktop\bench\claude\project\db\projectflow.db"

# ── Target ────────────────────────────────────────────────────────────────────
DST_DB = os.path.join(os.path.dirname(__file__), "demo.db")

# ── DDL for the projectflow schema in myDB ────────────────────────────────────
DDL = [
    """CREATE TABLE IF NOT EXISTS projectflow.workspaces (
        id         TEXT PRIMARY KEY,
        name       TEXT,
        slug       TEXT,
        owner      TEXT,
        created_at TEXT,
        project_ids TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS projectflow.projects (
        id                      TEXT PRIMARY KEY,
        workspace_id            TEXT,
        name                    TEXT,
        key                     TEXT,
        type                    TEXT,
        color                   TEXT,
        icon                    TEXT,
        description             TEXT,
        statuses                TEXT,
        members                 TEXT,
        default_sprint_duration INT,
        created_at              TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS projectflow.issues (
        id           TEXT PRIMARY KEY,
        project_id   TEXT,
        sprint_id    TEXT,
        epic_id      TEXT,
        parent_id    TEXT,
        key          TEXT,
        title        TEXT,
        description  TEXT,
        type         TEXT,
        status       TEXT,
        priority     TEXT,
        story_points INT,
        assignee_id  TEXT,
        reporter_id  TEXT,
        labels       TEXT,
        due_date     TEXT,
        created_at   TEXT,
        updated_at   TEXT,
        comments     TEXT,
        activity_log TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS projectflow.sprints (
        id         TEXT PRIMARY KEY,
        project_id TEXT,
        name       TEXT,
        goal       TEXT,
        start_date TEXT,
        end_date   TEXT,
        status     TEXT,
        velocity   FLOAT,
        created_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS projectflow.users (
        id            TEXT PRIMARY KEY,
        name          TEXT,
        email         TEXT,
        initials      TEXT,
        color         TEXT,
        role          TEXT,
        timezone      TEXT,
        created_at    TEXT,
        active        BOOL,
        password_hash TEXT,
        nav_permissions TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS projectflow.labels (
        id         TEXT PRIMARY KEY,
        project_id TEXT,
        name       TEXT,
        color      TEXT
    )""",
]

# ── Column mapping: SQLite col name → myDB col name ───────────────────────────
COL_MAP = {
    "workspaceId":            "workspace_id",
    "projectId":              "project_id",
    "sprintId":               "sprint_id",
    "epicId":                 "epic_id",
    "parentId":               "parent_id",
    "storyPoints":            "story_points",
    "assigneeId":             "assignee_id",
    "reporterId":             "reporter_id",
    "dueDate":                "due_date",
    "createdAt":              "created_at",
    "updatedAt":              "updated_at",
    "activityLog":            "activity_log",
    "projectIds":             "project_ids",
    "defaultSprintDuration":  "default_sprint_duration",
    "startDate":              "start_date",
    "endDate":                "end_date",
    "navPermissions":         "nav_permissions",
    "password_hash":          "password_hash",  # already snake_case
}

# ── JSON fields that must be serialized to string ─────────────────────────────
JSON_FIELDS = {
    "workspaces": ["projectIds"],
    "projects":   ["statuses", "members"],
    "issues":     ["labels", "comments", "activityLog"],
    "sprints":    [],
    "users":      ["navPermissions"],
    "labels":     [],
}


def _quote(v) -> str:
    """Produce a SQL literal for a Python value."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("'", "''")
    return f"'{s}'"


def migrate_table(src_conn, eng, src_table, dst_table, json_fields):
    src_conn.row_factory = sqlite3.Row
    rows = src_conn.execute(f"SELECT * FROM {src_table}").fetchall()
    if not rows:
        print(f"  {dst_table}: 0 rows — skipped")
        return 0

    count = 0
    for row in rows:
        r = dict(row)

        # Serialize JSON/list fields to JSON strings
        for f in json_fields:
            if f in r and r[f] is not None:
                if not isinstance(r[f], str):
                    r[f] = json.dumps(r[f], ensure_ascii=False)
            elif f in r:
                r[f] = "[]"

        # Rename camelCase → snake_case
        renamed = {}
        for k, v in r.items():
            renamed[COL_MAP.get(k, k)] = v

        cols = ", ".join(renamed.keys())
        vals = ", ".join(_quote(v) for v in renamed.values())
        sql  = f"INSERT INTO {dst_table} ({cols}) VALUES ({vals})"
        try:
            eng.execute(parse_one(sql))
            count += 1
        except Exception as e:
            print(f"  ⚠  {dst_table} row {r.get('id','?')}: {e}")

    print(f"  {dst_table}: {count}/{len(rows)} rows migrated")
    return count


def main():
    if not os.path.exists(SRC_DB):
        print(f"ERROR: source DB not found at {SRC_DB}")
        sys.exit(1)

    print(f"Source : {SRC_DB}")
    print(f"Target : {DST_DB}")
    print()

    src_conn = sqlite3.connect(SRC_DB)
    eng = Engine(DST_DB)

    # Create schema tables
    print("Creating projectflow schema tables…")
    for ddl in DDL:
        eng.execute(parse_one(ddl))
    print("  Done.\n")

    # Migrate each table
    print("Migrating data…")
    tables = [
        ("workspaces", "projectflow.workspaces"),
        ("projects",   "projectflow.projects"),
        ("issues",     "projectflow.issues"),
        ("sprints",    "projectflow.sprints"),
        ("users",      "projectflow.users"),
        ("labels",     "projectflow.labels"),
    ]
    total = 0
    for src_t, dst_t in tables:
        total += migrate_table(src_conn, eng, src_t, dst_t, JSON_FIELDS.get(src_t, []))

    src_conn.close()
    eng.close()

    print(f"\n✓ Migration complete — {total} rows written to myDB")


if __name__ == "__main__":
    main()
