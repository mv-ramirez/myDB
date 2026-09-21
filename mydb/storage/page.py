"""
Storage layer — Page format.

File layout: fixed-size 8 KB pages packed sequentially in the .db file.

Page layout (8192 bytes):
  [0:32]   Header  — page_id, next_page_id, num_slots, free_start,
                      free_end, page_type, flags, 16 reserved bytes
  [32:N]   Slot array — grows forward, 4 bytes per slot (offset+length)
  [N:M]    Free space
  [M:8192] Row data  — grows backward from the end of the page
"""
import struct
import zlib

PAGE_SIZE        = 8192
PAGE_HEADER_SIZE = 32
SLOT_SIZE        = 4   # 2-byte offset + 2-byte length

# page_id(4) next_page_id(4) num_slots(2) free_start(2) free_end(2)
# page_type(1) flags(1) + 16 reserved bytes = 32 total
_HDR = struct.Struct("!IIHHHBBxxxxxxxxxxxxxxxx")

# slot: row_offset(2) row_length(2)
_SLOT = struct.Struct("!HH")

# Page types
PAGE_FREE  = 0
PAGE_DATA  = 1
PAGE_INDEX = 2
PAGE_META  = 3

# Flags
FLAG_DIRTY = 0x01


class Page:
    __slots__ = (
        "page_id", "next_page_id", "num_slots", "free_start",
        "free_end", "page_type", "flags", "_data", "dirty",
    )

    def __init__(self, page_id: int, page_type: int = PAGE_DATA):
        self.page_id     = page_id
        self.next_page_id = 0
        self.num_slots   = 0
        self.free_start  = PAGE_HEADER_SIZE  # first byte after header
        self.free_end    = PAGE_SIZE          # first byte of row data area
        self.page_type   = page_type
        self.flags       = 0
        self._data       = bytearray(PAGE_SIZE)
        self.dirty       = False
        self._flush_header()

    # ── Header ────────────────────────────────────────────────────────────────

    def _flush_header(self):
        _HDR.pack_into(
            self._data, 0,
            self.page_id, self.next_page_id,
            self.num_slots, self.free_start, self.free_end,
            self.page_type, self.flags,
        )

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> "Page":
        p = cls.__new__(cls)
        p._data  = bytearray(data)
        p.dirty  = False
        (
            p.page_id, p.next_page_id,
            p.num_slots, p.free_start, p.free_end,
            p.page_type, p.flags,
        ) = _HDR.unpack_from(p._data, 0)
        return p

    def to_bytes(self) -> bytes:
        self._flush_header()
        return bytes(self._data)

    # ── Free space ────────────────────────────────────────────────────────────

    @property
    def free_space(self) -> int:
        return self.free_end - self.free_start

    def can_fit(self, row_bytes: int) -> bool:
        return self.free_space >= row_bytes + SLOT_SIZE

    # ── Slot management ───────────────────────────────────────────────────────

    def _slot_offset(self, slot_idx: int) -> int:
        return PAGE_HEADER_SIZE + slot_idx * SLOT_SIZE

    def _read_slot(self, slot_idx: int) -> tuple[int, int]:
        off = self._slot_offset(slot_idx)
        return _SLOT.unpack_from(self._data, off)

    def _write_slot(self, slot_idx: int, row_offset: int, row_length: int):
        off = self._slot_offset(slot_idx)
        _SLOT.pack_into(self._data, off, row_offset, row_length)

    # ── Row insert ────────────────────────────────────────────────────────────

    def insert_row(self, row_data: bytes) -> int:
        """Insert row and return slot index. Raises if page is full."""
        if not self.can_fit(len(row_data)):
            raise ValueError("Page full")
        row_len    = len(row_data)
        row_offset = self.free_end - row_len
        self._data[row_offset: row_offset + row_len] = row_data
        slot_idx   = self.num_slots
        self._write_slot(slot_idx, row_offset, row_len)
        self.free_end   = row_offset
        self.free_start = self._slot_offset(slot_idx + 1)
        self.num_slots += 1
        self.dirty = True
        self._flush_header()
        return slot_idx

    # ── Row read / update / delete ────────────────────────────────────────────

    def get_row(self, slot_idx: int) -> bytes | None:
        if slot_idx >= self.num_slots:
            return None
        row_offset, row_length = self._read_slot(slot_idx)
        if row_length == 0:
            return None  # deleted
        return bytes(self._data[row_offset: row_offset + row_length])

    def delete_row(self, slot_idx: int) -> bool:
        if slot_idx >= self.num_slots:
            return False
        row_offset, _ = self._read_slot(slot_idx)
        self._write_slot(slot_idx, row_offset, 0)  # length=0 marks deletion
        self.dirty = True
        self._flush_header()
        return True

    def update_row(self, slot_idx: int, new_data: bytes) -> bool:
        """In-place update only if new data fits in the same slot area."""
        if slot_idx >= self.num_slots:
            return False
        row_offset, row_length = self._read_slot(slot_idx)
        if row_length == 0:
            return False
        if len(new_data) > row_length:
            return False
        self._data[row_offset: row_offset + len(new_data)] = new_data
        self._write_slot(slot_idx, row_offset, len(new_data))
        self.dirty = True
        self._flush_header()
        return True

    # ── Iteration ─────────────────────────────────────────────────────────────

    def iter_rows(self):
        """Yield (slot_idx, row_bytes) for all live rows."""
        for i in range(self.num_slots):
            row = self.get_row(i)
            if row is not None:
                yield i, row
