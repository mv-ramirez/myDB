"""
Execution engine — walks the AST and produces result rows.

Implements the Volcano (iterator) model:
  execute(stmt) → list of dicts  (each dict is one result row)

Supports:
  SELECT  (with WHERE, ORDER BY, LIMIT/OFFSET, GROUP BY + aggregates)
  INSERT / UPDATE / DELETE
  CREATE TABLE / DROP TABLE / CREATE INDEX
"""
import os
from mydb.sql.ast_nodes import (
    SelectStmt, UnionStmt, InsertStmt, UpdateStmt, DeleteStmt,
    CreateTableStmt, DropTableStmt, AlterTableStmt, CreateIndexStmt,
    Star, Alias, ColRef, FuncCall, NullLit, IntLit,
    BoolLit, FloatLit, StrLit,
    SubqueryRef, JoinClause,
)
from mydb.catalog.catalog import SystemCatalog, TableSchema, ColumnDef
from mydb.storage.buffer import BufferPool
from mydb.storage.heap import HeapFile
from mydb.storage.serializer import ColType
from .expr import ExprEvaluator


class Engine:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._dir     = os.path.dirname(os.path.abspath(db_path)) or "."
        self._catalog = SystemCatalog(db_path)
        self._pool    = BufferPool(capacity=256)
        self._heaps:  dict[str, HeapFile] = {}
        self._eval    = ExprEvaluator(engine=self)

    # ── Public API ────────────────────────────────────────────────────────────

    def execute(self, stmt) -> list[dict]:
        t = type(stmt)
        if t is SelectStmt:      return self._select(stmt)
        if t is UnionStmt:       return self._union(stmt)
        if t is InsertStmt:      return self._insert(stmt)
        if t is UpdateStmt:      return self._update(stmt)
        if t is DeleteStmt:      return self._delete(stmt)
        if t is CreateTableStmt: return self._create_table(stmt)
        if t is DropTableStmt:   return self._drop_table(stmt)
        if t is CreateIndexStmt: return self._create_index(stmt)
        if t is AlterTableStmt:  return self._alter_table(stmt)
        raise NotImplementedError(f"Unsupported statement: {t.__name__}")

    def close(self):
        self._pool.flush_all()
        self._pool.close_all()

    # ── Heap file access ──────────────────────────────────────────────────────

    def _heap_path(self, table_name: str) -> str:
        safe = table_name.lower().replace(".", "__")
        return os.path.join(self._dir, f"{safe}.heap")

    def _heap(self, table_name: str) -> HeapFile:
        key = table_name.lower()
        if key not in self._heaps:
            schema = self._catalog.get_table(key)
            if not schema:
                raise ValueError(f"Table '{table_name}' does not exist")
            self._heaps[key] = HeapFile(self._heap_path(key), schema.col_types(), self._pool)
        return self._heaps[key]

    # ── Query dispatch (handles both SELECT and UNION) ────────────────────────

    def _exec_query(self, stmt, outer_row: dict | None = None) -> list[dict]:
        if isinstance(stmt, UnionStmt):
            return self._union(stmt, outer_row=outer_row)
        return self._select(stmt, outer_row=outer_row)

    # ── UNION / INTERSECT / EXCEPT ────────────────────────────────────────────

    @staticmethod
    def _row_key(row: dict):
        return tuple(sorted((k, str(v)) for k, v in row.items()))

    def _union(self, stmt: UnionStmt, outer_row: dict | None = None) -> list[dict]:
        result = self._exec_query(stmt.selects[0], outer_row=outer_row)
        left_cols = list(result[0].keys()) if result else []

        for i, sel in enumerate(stmt.selects[1:]):
            right = self._exec_query(sel, outer_row=outer_row)

            # Normalize right column names to match left's by position
            if left_cols and right:
                right = [dict(zip(left_cols, row.values())) for row in right]

            utype = stmt.union_types[i]

            if utype == 'UNION ALL':
                result = result + right
                continue

            right_keys = {self._row_key(r) for r in right}
            seen   = set()
            merged = []

            candidates = result + right if utype == 'UNION' else result
            for row in candidates:
                key = self._row_key(row)
                if key in seen:
                    continue
                if utype == 'UNION':
                    include = True
                elif utype == 'INTERSECT':
                    include = key in right_keys
                else:   # EXCEPT
                    include = key not in right_keys
                if include:
                    seen.add(key)
                    merged.append(row)
            result = merged
        return result

    # ── SELECT ────────────────────────────────────────────────────────────────

    def _select(self, stmt: SelectStmt, outer_row: dict | None = None) -> list[dict]:
        # 1. Scan source table
        if stmt.from_ is None:
            rows = [outer_row.copy() if outer_row else {}]
        elif isinstance(stmt.from_, SubqueryRef):
            inner_rows = self._exec_query(stmt.from_.query, outer_row=outer_row)
            alias = stmt.from_.alias.lower()
            rows = []
            for inner_row in inner_rows:
                row = dict(outer_row) if outer_row else {}
                for k, v in inner_row.items():
                    row[k] = v
                    row[f"{alias}.{k}"] = v
                rows.append(row)
        else:
            schema = self._catalog.get_table(stmt.from_.name)
            if schema is None:
                raise ValueError(f"Table '{stmt.from_.name}' does not exist")
            alias  = (stmt.from_.alias or stmt.from_.name).lower()
            heap   = self._heap(stmt.from_.name)
            rows   = []
            for _, values in heap.scan():
                row = dict(outer_row) if outer_row else {}
                for col, val in zip(schema.col_names(), values):
                    row[col.lower()]               = val
                    row[f"{alias}.{col.lower()}"]  = val
                rows.append(row)

        # 2. JOINs
        for join in stmt.joins:
            jt = join.table
            j_schema = self._catalog.get_table(jt.name)
            if j_schema is None:
                raise ValueError(f"Table '{jt.name}' does not exist")
            j_alias = (jt.alias or jt.name).lower()
            j_heap  = self._heap(jt.name)

            # Build all right-side rows
            right_rows = []
            for _, values in j_heap.scan():
                jr = {}
                for col, val in zip(j_schema.col_names(), values):
                    jr[col.lower()]               = val
                    jr[f"{j_alias}.{col.lower()}"] = val
                right_rows.append(jr)

            jtype = join.join_type  # INNER | LEFT | RIGHT | CROSS
            new_rows = []

            if jtype in ("INNER", "CROSS", ""):
                for lr in rows:
                    for rr in right_rows:
                        combined = {**lr, **rr}
                        if join.condition is None or self._eval.eval(join.condition, combined):
                            new_rows.append(combined)

            elif jtype == "LEFT":
                null_right = {k: None for k in (right_rows[0] if right_rows else {})}
                for lr in rows:
                    matched = False
                    for rr in right_rows:
                        combined = {**lr, **rr}
                        if join.condition is None or self._eval.eval(join.condition, combined):
                            new_rows.append(combined)
                            matched = True
                    if not matched:
                        new_rows.append({**lr, **null_right})

            elif jtype == "RIGHT":
                null_left = {k: None for k in (rows[0] if rows else {})}
                for rr in right_rows:
                    matched = False
                    for lr in rows:
                        combined = {**lr, **rr}
                        if join.condition is None or self._eval.eval(join.condition, combined):
                            new_rows.append(combined)
                            matched = True
                    if not matched:
                        new_rows.append({**null_left, **rr})

            rows = new_rows

        # 3. WHERE filter
        if stmt.where is not None:
            rows = [r for r in rows if self._eval.eval(stmt.where, r)]

        # 4. GROUP BY + aggregates
        has_agg = stmt.group_by or self._has_aggregate(stmt.columns)
        if has_agg:
            rows = self._aggregate(stmt, rows)
        else:
            # HAVING without GROUP BY (rare but valid)
            if stmt.having is not None:
                rows = [r for r in rows if self._eval.eval(stmt.having, r)]

        # 4. ORDER BY
        for item in reversed(stmt.order_by):
            rows.sort(key=lambda r: self._sort_key(item.expr, r), reverse=not item.asc)

        # 5. LIMIT / OFFSET
        if stmt.offset:
            rows = rows[stmt.offset:]
        if stmt.limit is not None:
            rows = rows[:stmt.limit]

        # 6. Project columns
        return [self._project(stmt.columns, r) for r in rows]

    _AGG_FUNCS = frozenset(("COUNT", "SUM", "AVG", "MIN", "MAX"))

    def _project(self, columns, row: dict) -> dict:
        if columns and isinstance(columns[0], Star):
            return {k: v for k, v in row.items() if "." not in k}

        result = {}
        for i, col in enumerate(columns):
            if isinstance(col, Star):
                result.update({k: v for k, v in row.items() if "." not in k})
            elif isinstance(col, Alias):
                inner = col.expr
                if isinstance(inner, FuncCall) and inner.name in self._AGG_FUNCS:
                    result[col.alias] = row.get(col.alias)
                else:
                    result[col.alias] = self._eval.eval(inner, row)
            elif isinstance(col, FuncCall) and col.name in self._AGG_FUNCS:
                key = col.name.lower()
                result[key] = row.get(key)
            elif isinstance(col, ColRef):
                key = col.name.lower()
                result[key] = self._eval.eval(col, row)
            elif isinstance(col, FuncCall):
                result[col.name.lower()] = self._eval.eval(col, row)
            else:
                val = self._eval.eval(col, row)
                result[f"col_{i + 1}"] = val   # anonymous expression → col_N
        return result

    def _sort_key(self, expr, row):
        v = self._eval.eval(expr, row)
        if v is None:
            return (1, None)
        return (0, v)

    # ── Aggregates ────────────────────────────────────────────────────────────

    def _has_aggregate(self, columns) -> bool:
        for col in columns:
            expr = col.expr if isinstance(col, Alias) else col
            if isinstance(expr, FuncCall) and expr.name in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
                return True
        return False

    def _aggregate(self, stmt: SelectStmt, rows: list[dict]) -> list[dict]:
        from collections import defaultdict

        def group_key(row):
            if not stmt.group_by:
                return "__all__"
            return tuple(self._eval.eval(e, row) for e in stmt.group_by)

        # SQL requires aggregate-only queries (no GROUP BY) to return exactly
        # one row even when the input is empty, e.g. COUNT(*) = 0.
        if not rows and not stmt.group_by:
            agg_row = {}
            for col in stmt.columns:
                expr  = col.expr if isinstance(col, Alias) else col
                alias = col.alias if isinstance(col, Alias) else None
                if isinstance(expr, FuncCall) and expr.name in self._AGG_FUNCS:
                    agg_val = self._compute_agg(expr, [])
                    out_key = alias or expr.name.lower()
                    agg_row[out_key] = agg_val
                    if alias:
                        agg_row[expr.name.lower()] = agg_val
            return [agg_row]

        groups: dict = defaultdict(list)
        for row in rows:
            groups[group_key(row)].append(row)

        result = []
        for key, group_rows in groups.items():
            agg_row = {}
            # copy group-by columns into agg_row
            if stmt.group_by and group_rows:
                for e in stmt.group_by:
                    v = self._eval.eval(e, group_rows[0])
                    name = e.name.lower() if isinstance(e, ColRef) else str(e)
                    agg_row[name] = v

            # compute aggregates
            for col in stmt.columns:
                expr  = col.expr if isinstance(col, Alias) else col
                alias = col.alias if isinstance(col, Alias) else None

                if isinstance(expr, FuncCall) and expr.name in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
                    agg_val = self._compute_agg(expr, group_rows)
                    out_key = alias or expr.name.lower()
                    agg_row[out_key] = agg_val
                    if alias:  # also store under fn name so HAVING count(*) > N works
                        agg_row[expr.name.lower()] = agg_val
                elif not isinstance(col, Star):
                    # passthrough non-aggregate expression
                    if group_rows:
                        v = self._eval.eval(expr, group_rows[0])
                        out_key = alias or (expr.name.lower() if isinstance(expr, ColRef) else str(expr))
                        agg_row[out_key] = v

            if stmt.having is None or self._eval.eval(stmt.having, agg_row):
                result.append(agg_row)

        return result

    def _compute_agg(self, func: FuncCall, rows: list[dict]):
        name = func.name.upper()
        is_star = not func.args or isinstance(func.args[0], Star)

        if name == "COUNT":
            if is_star:
                return len(rows)
            vals = [self._eval.eval(func.args[0], r) for r in rows]
            return sum(1 for v in vals if v is not None)

        vals = [self._eval.eval(func.args[0], r) for r in rows if r]
        vals = [v for v in vals if v is not None]

        if name == "SUM":   return sum(vals) if vals else None
        if name == "AVG":   return sum(vals) / len(vals) if vals else None
        if name == "MIN":   return min(vals) if vals else None
        if name == "MAX":   return max(vals) if vals else None

    # ── INSERT ────────────────────────────────────────────────────────────────

    def _insert(self, stmt: InsertStmt) -> list[dict]:
        schema = self._catalog.get_table(stmt.table)
        if schema is None:
            raise ValueError(f"Table '{stmt.table}' does not exist")
        heap   = self._heap(stmt.table)
        count  = 0
        for row_vals in stmt.rows:
            values = self._build_row(schema, stmt.columns, row_vals)
            heap.insert(values)
            count += 1
        heap.flush()
        return [{"rows_affected": count}]

    def _build_row(self, schema: TableSchema, col_names: list, values: list) -> list:
        row = [None] * len(schema.columns)
        name_to_idx = {c.name.lower(): i for i, c in enumerate(schema.columns)}
        for col_name, val in zip(col_names, values):
            idx = name_to_idx.get(col_name.lower())
            if idx is None:
                raise ValueError(f"Column '{col_name}' does not exist in '{schema.name}'")
            row[idx] = self._coerce(val, schema.columns[idx].col_type)
        # apply defaults for columns not provided
        for i, col in enumerate(schema.columns):
            if row[i] is None and col.default is not None:
                row[i] = col.default
        return row

    def _coerce(self, val, col_type: ColType):
        if val is None:
            return None
        if col_type == ColType.INT:    return int(val)
        if col_type == ColType.BIGINT: return int(val)
        if col_type == ColType.FLOAT:  return float(val)
        if col_type == ColType.BOOL:   return bool(val)
        if col_type == ColType.TEXT:   return str(val)
        return val

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def _update(self, stmt: UpdateStmt) -> list[dict]:
        schema = self._catalog.get_table(stmt.table)
        if schema is None:
            raise ValueError(f"Table '{stmt.table}' does not exist")
        heap  = self._heap(stmt.table)
        count = 0
        for rid, values in list(heap.scan()):
            row = {c.lower(): v for c, v in zip(schema.col_names(), values)}
            if stmt.where is not None and not self._eval.eval(stmt.where, row):
                continue
            new_values = list(values)
            for asgn in stmt.assignments:
                idx = schema.col_index(asgn.column)
                new_val = self._eval.eval(asgn.value, row)
                new_values[idx] = self._coerce(new_val, schema.columns[idx].col_type)
            heap.update(rid, new_values)
            count += 1
        heap.flush()
        return [{"rows_affected": count}]

    # ── DELETE ────────────────────────────────────────────────────────────────

    def _delete(self, stmt: DeleteStmt) -> list[dict]:
        schema = self._catalog.get_table(stmt.table)
        if schema is None:
            raise ValueError(f"Table '{stmt.table}' does not exist")
        heap  = self._heap(stmt.table)
        count = 0
        for rid, values in list(heap.scan()):
            row = {c.lower(): v for c, v in zip(schema.col_names(), values)}
            if stmt.where is None or self._eval.eval(stmt.where, row):
                heap.delete(rid)
                count += 1
        heap.flush()
        return [{"rows_affected": count}]

    # ── DDL ───────────────────────────────────────────────────────────────────

    def _create_table(self, stmt: CreateTableStmt) -> list[dict]:
        columns = []
        for c in stmt.columns:
            col_type = SystemCatalog.parse_col_type(c.type_name)
            columns.append(ColumnDef(
                name        = c.name,
                col_type    = col_type,
                nullable    = not c.not_null,
                primary_key = c.primary_key,
                unique      = c.unique,
                default     = c.default,
            ))
        schema = TableSchema(name=stmt.table, columns=columns)
        created = self._catalog.create_table(schema, if_not_exists=stmt.if_not_exists)
        # pre-create the heap file
        if created:
            self._heap(stmt.table)
        return [{"result": "created" if created else "already_exists"}]

    def _drop_table(self, stmt: DropTableStmt) -> list[dict]:
        dropped = self._catalog.drop_table(stmt.table, if_exists=stmt.if_exists)
        if dropped:
            key  = stmt.table.lower()
            path = self._heap_path(key)
            self._heaps.pop(key, None)
            self._pool.close_file(path)
            if os.path.exists(path):
                os.remove(path)
        return [{"result": "dropped" if dropped else "not_found"}]

    def _alter_table(self, stmt: AlterTableStmt) -> list[dict]:
        schema = self._catalog.get_table(stmt.table)
        if schema is None:
            raise ValueError(f"Table '{stmt.table}' does not exist")

        action = stmt.action[0]

        if action == 'RENAME_TABLE':
            new_name  = stmt.action[1]
            old_key   = stmt.table.lower()
            old_path  = self._heap_path(old_key)
            new_path  = self._heap_path(new_name.lower())
            self._heaps.pop(old_key, None)
            self._pool.close_file(old_path)
            schema.name = new_name
            self._catalog._tables.pop(old_key)
            self._catalog._tables[new_name.lower()] = schema
            self._catalog._save()
            if os.path.exists(old_path):
                os.rename(old_path, new_path)
            return [{"result": "table_renamed"}]

        if action == 'RENAME_COLUMN':
            old_col, new_col = stmt.action[1], stmt.action[2]
            idx = schema.col_index(old_col)
            schema.columns[idx].name = new_col
            self._catalog._save()
            self._heaps.pop(stmt.table.lower(), None)
            return [{"result": "column_renamed"}]

        if action in ('ADD_COLUMN', 'DROP_COLUMN'):
            return self._rewrite_heap(stmt, schema, action)

        raise ValueError(f"Unknown ALTER TABLE action: {action}")

    def _rewrite_heap(self, stmt: AlterTableStmt, schema, action: str) -> list[dict]:
        key       = stmt.table.lower()
        heap_path = self._heap_path(key)
        tmp_path  = heap_path + ".tmp"

        old_heap = self._heap(stmt.table)
        old_rows = list(old_heap.scan())  # [(RowID, values), ...]

        if action == 'ADD_COLUMN':
            col_def_ast = stmt.action[1]
            col_type    = SystemCatalog.parse_col_type(col_def_ast.type_name)
            new_col = ColumnDef(
                name        = col_def_ast.name,
                col_type    = col_type,
                nullable    = not col_def_ast.not_null,
                primary_key = col_def_ast.primary_key,
                unique      = col_def_ast.unique,
                default     = col_def_ast.default,
            )
            schema.columns.append(new_col)
            default_val = self._coerce(new_col.default, col_type)
            new_col_types = schema.col_types()
            transform = lambda vals, d=default_val: list(vals) + [d]

        elif action == 'DROP_COLUMN':
            col_name = stmt.action[1]
            drop_idx = schema.col_index(col_name)
            schema.columns.pop(drop_idx)
            new_col_types = schema.col_types()
            transform = lambda vals, i=drop_idx: [v for j, v in enumerate(vals) if j != i]

        tmp_heap = HeapFile(tmp_path, new_col_types, self._pool)
        for _, values in old_rows:
            tmp_heap.insert(transform(values))
        tmp_heap.flush()

        self._heaps.pop(key, None)
        self._pool.close_file(heap_path)
        self._pool.close_file(tmp_path)
        os.replace(tmp_path, heap_path)

        self._catalog._save()
        return [{"result": "altered"}]

    def _create_index(self, stmt: CreateIndexStmt) -> list[dict]:
        # Index metadata stored in catalog; B-tree implementation in future milestone
        schema = self._catalog.get_table(stmt.table)
        if schema is None:
            raise ValueError(f"Table '{stmt.table}' does not exist")
        from mydb.catalog.catalog import IndexDef
        idx = IndexDef(stmt.name, stmt.table, stmt.columns, stmt.unique)
        schema.indexes.append(idx)
        self._catalog._save()
        return [{"result": "index_created"}]
