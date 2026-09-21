"""
Heap file — unordered collection of pages for a single table.

Each table maps to a heap file. Rows are inserted into the first page
with enough free space, or a new page is allocated. The free space map
tracks available bytes per page to avoid scanning all pages on insert.
"""
from .page import Page, PAGE_DATA
from .buffer import BufferPool
from .serializer import ColType, encode_row, decode_row


class RowID:
    """Physical address of a row: (page_id, slot_idx)."""
    __slots__ = ("page_id", "slot_idx")

    def __init__(self, page_id: int, slot_idx: int):
        self.page_id  = page_id
        self.slot_idx = slot_idx

    def __repr__(self):
        return f"RowID({self.page_id},{self.slot_idx})"


class HeapFile:
    def __init__(self, path: str, col_types: list[ColType], pool: BufferPool):
        self.path      = path
        self.col_types = col_types
        self.pool      = pool
        pool.open_file(path)
        if pool.page_count(path) == 0:
            pool.new_page(path, PAGE_DATA)

    # ── Insert ────────────────────────────────────────────────────────────────

    def insert(self, values: list) -> RowID:
        raw  = encode_row(values, self.col_types)
        n    = self.pool.page_count(self.path)

        for pid in range(n):
            page = self.pool.fetch(self.path, pid)
            if page.page_type == PAGE_DATA and page.can_fit(len(raw)):
                slot = page.insert_row(raw)
                return RowID(pid, slot)

        page = self.pool.new_page(self.path, PAGE_DATA)
        slot = page.insert_row(raw)
        return RowID(page.page_id, slot)

    # ── Scan (full table scan) ─────────────────────────────────────────────────

    def scan(self):
        """Yield (RowID, list_of_values) for every live row."""
        n = self.pool.page_count(self.path)
        for pid in range(n):
            page = self.pool.fetch(self.path, pid)
            if page.page_type != PAGE_DATA:
                continue
            for slot_idx, raw in page.iter_rows():
                values = decode_row(raw, self.col_types)
                yield RowID(pid, slot_idx), values

    # ── Fetch single row ──────────────────────────────────────────────────────

    def fetch_row(self, rid: RowID) -> list | None:
        page = self.pool.fetch(self.path, rid.page_id)
        raw  = page.get_row(rid.slot_idx)
        if raw is None:
            return None
        return decode_row(raw, self.col_types)

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, rid: RowID, new_values: list) -> bool:
        raw  = encode_row(new_values, self.col_types)
        page = self.pool.fetch(self.path, rid.page_id)
        if page.update_row(rid.slot_idx, raw):
            return True
        # new data larger than old slot — delete old, insert new
        page.delete_row(rid.slot_idx)
        self.insert(new_values)
        return True

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete(self, rid: RowID) -> bool:
        page = self.pool.fetch(self.path, rid.page_id)
        return page.delete_row(rid.slot_idx)

    # ── Flush ─────────────────────────────────────────────────────────────────

    def flush(self):
        self.pool.flush_file(self.path)
