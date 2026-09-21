"""
System catalog — persisted registry of all tables, columns, and indexes.

Stored as a JSON sidecar file (<db_path>.catalog.json) alongside the .db file.
Loaded into memory at open; written on every DDL change.
"""
import json
import os
from dataclasses import dataclass, field, asdict
from mydb.storage.serializer import ColType, SQL_TYPE_MAP


@dataclass
class ColumnDef:
    name:       str
    col_type:   ColType
    nullable:   bool  = True
    primary_key: bool = False
    unique:     bool  = False
    default:    object = None

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "col_type":    int(self.col_type),
            "nullable":    self.nullable,
            "primary_key": self.primary_key,
            "unique":      self.unique,
            "default":     self.default,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ColumnDef":
        return cls(
            name        = d["name"],
            col_type    = ColType(d["col_type"]),
            nullable    = d.get("nullable", True),
            primary_key = d.get("primary_key", False),
            unique      = d.get("unique", False),
            default     = d.get("default"),
        )


@dataclass
class IndexDef:
    name:    str
    table:   str
    columns: list[str]
    unique:  bool = False


@dataclass
class TableSchema:
    name:    str
    columns: list[ColumnDef] = field(default_factory=list)
    indexes: list[IndexDef]  = field(default_factory=list)

    def col_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def col_types(self) -> list[ColType]:
        return [c.col_type for c in self.columns]

    def col_index(self, name: str) -> int:
        name_lower = name.lower()
        for i, c in enumerate(self.columns):
            if c.name.lower() == name_lower:
                return i
        raise KeyError(f"Column '{name}' not found in table '{self.name}'")

    def to_dict(self) -> dict:
        return {
            "name":    self.name,
            "columns": [c.to_dict() for c in self.columns],
            "indexes": [
                {"name": ix.name, "table": ix.table,
                 "columns": ix.columns, "unique": ix.unique}
                for ix in self.indexes
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TableSchema":
        return cls(
            name    = d["name"],
            columns = [ColumnDef.from_dict(c) for c in d["columns"]],
            indexes = [
                IndexDef(
                    name    = ix["name"],
                    table   = ix["table"],
                    columns = ix["columns"],
                    unique  = ix.get("unique", False),
                )
                for ix in d.get("indexes", [])
            ],
        )


class SystemCatalog:
    def __init__(self, db_path: str):
        self._db_path  = db_path
        self._cat_path = db_path + ".catalog.json"
        self._tables: dict[str, TableSchema] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        if os.path.exists(self._cat_path):
            with open(self._cat_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for td in data.get("tables", []):
                schema = TableSchema.from_dict(td)
                self._tables[schema.name.lower()] = schema

    def _save(self):
        data = {"tables": [t.to_dict() for t in self._tables.values()]}
        with open(self._cat_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # ── Table operations ──────────────────────────────────────────────────────

    def create_table(self, schema: TableSchema, if_not_exists: bool = False) -> bool:
        key = schema.name.lower()
        if key in self._tables:
            if if_not_exists:
                return False
            raise ValueError(f"Table '{schema.name}' already exists")
        self._tables[key] = schema
        self._save()
        return True

    def drop_table(self, name: str, if_exists: bool = False) -> bool:
        key = name.lower()
        if key not in self._tables:
            if if_exists:
                return False
            raise ValueError(f"Table '{name}' does not exist")
        del self._tables[key]
        self._save()
        return True

    def get_table(self, name: str) -> TableSchema | None:
        return self._tables.get(name.lower())

    def table_exists(self, name: str) -> bool:
        return name.lower() in self._tables

    def list_tables(self) -> list[str]:
        return [s.name for s in self._tables.values()]

    # ── Helper: parse SQL type string → ColType ───────────────────────────────

    @staticmethod
    def parse_col_type(type_str: str) -> ColType:
        key = type_str.upper().split("(")[0].strip()
        if key not in SQL_TYPE_MAP:
            raise ValueError(f"Unknown column type: '{type_str}'")
        return SQL_TYPE_MAP[key]
