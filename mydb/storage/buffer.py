"""
Buffer pool — in-memory LRU cache of pages.

Pages are evicted when the pool is full; dirty pages are flushed to disk
before eviction. All disk I/O is routed through the buffer pool.
"""
from collections import OrderedDict
from .page import Page, PAGE_SIZE


class BufferPool:
    def __init__(self, capacity: int = 256):
        self._capacity = capacity
        self._cache: OrderedDict[tuple, Page] = OrderedDict()  # (file_path, page_id) → Page
        self._file_handles: dict[str, object] = {}

    # ── File handles ──────────────────────────────────────────────────────────

    def open_file(self, path: str):
        if path not in self._file_handles:
            import io, os
            if not os.path.exists(path):
                open(path, "wb").close()
            self._file_handles[path] = open(path, "r+b", buffering=0)

    def close_file(self, path: str):
        self.flush_file(path)
        fh = self._file_handles.pop(path, None)
        if fh:
            fh.close()
        keys = [k for k in self._cache if k[0] == path]
        for k in keys:
            del self._cache[k]

    def _fh(self, path: str):
        if path not in self._file_handles:
            self.open_file(path)
        return self._file_handles[path]

    # ── Page count ────────────────────────────────────────────────────────────

    def page_count(self, path: str) -> int:
        import os
        size = os.path.getsize(path)
        return size // PAGE_SIZE

    # ── Fetch page ────────────────────────────────────────────────────────────

    def fetch(self, path: str, page_id: int) -> Page:
        key = (path, page_id)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        fh  = self._fh(path)
        fh.seek(page_id * PAGE_SIZE)
        raw = fh.read(PAGE_SIZE)
        if len(raw) < PAGE_SIZE:
            raise ValueError(f"Page {page_id} does not exist in {path}")
        page = Page.from_bytes(raw)
        self._insert(key, page)
        return page

    # ── Allocate new page ─────────────────────────────────────────────────────

    def new_page(self, path: str, page_type: int = 1) -> Page:
        fh      = self._fh(path)
        page_id = self.page_count(path)
        page    = Page(page_id, page_type)
        fh.seek(page_id * PAGE_SIZE)
        fh.write(page.to_bytes())
        fh.flush()
        key = (path, page_id)
        self._insert(key, page)
        return page

    # ── Flush ─────────────────────────────────────────────────────────────────

    def flush_page(self, path: str, page_id: int):
        key  = (path, page_id)
        page = self._cache.get(key)
        if page and page.dirty:
            fh = self._fh(path)
            fh.seek(page_id * PAGE_SIZE)
            fh.write(page.to_bytes())
            fh.flush()
            page.dirty = False

    def flush_file(self, path: str):
        for (p, pid), page in list(self._cache.items()):
            if p == path and page.dirty:
                self.flush_page(p, pid)

    def flush_all(self):
        for (path, page_id), page in list(self._cache.items()):
            if page.dirty:
                self.flush_page(path, page_id)

    # ── LRU eviction ──────────────────────────────────────────────────────────

    def _insert(self, key: tuple, page: Page):
        if len(self._cache) >= self._capacity:
            evict_key, evict_page = next(iter(self._cache.items()))
            if evict_page.dirty:
                self.flush_page(evict_key[0], evict_key[1])
            del self._cache[evict_key]
        self._cache[key] = page

    def close_all(self):
        self.flush_all()
        for fh in self._file_handles.values():
            fh.close()
        self._file_handles.clear()
        self._cache.clear()
