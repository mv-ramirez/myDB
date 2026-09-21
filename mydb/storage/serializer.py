"""
Row serializer — encodes Python values to bytes and decodes them back.

Row wire format:
  [null_bitmap: ceil(ncols/8) bytes]
  [fixed columns: raw bytes in column order, skipped if NULL]
  [var lengths:   uint16 per variable-width column, 0 if NULL]
  [var data:      raw bytes for each variable-width column]
"""
import struct
import math
from enum import IntEnum

# ── Column types ──────────────────────────────────────────────────────────────

class ColType(IntEnum):
    INT     = 1   # 4-byte signed int
    BIGINT  = 2   # 8-byte signed int
    FLOAT   = 3   # 8-byte double
    BOOL    = 4   # 1 byte
    TEXT    = 5   # variable UTF-8
    BLOB    = 6   # variable bytes

FIXED_SIZES = {
    ColType.INT:    4,
    ColType.BIGINT: 8,
    ColType.FLOAT:  8,
    ColType.BOOL:   1,
}

FIXED_STRUCTS = {
    ColType.INT:    struct.Struct("!i"),
    ColType.BIGINT: struct.Struct("!q"),
    ColType.FLOAT:  struct.Struct("!d"),
    ColType.BOOL:   struct.Struct("!?"),
}

VAR_LEN_STRUCT = struct.Struct("!H")  # uint16 length prefix

SQL_TYPE_MAP = {
    "INT": ColType.INT, "INTEGER": ColType.INT,
    "BIGINT": ColType.BIGINT,
    "FLOAT": ColType.FLOAT, "REAL": ColType.FLOAT, "DOUBLE": ColType.FLOAT,
    "BOOL": ColType.BOOL, "BOOLEAN": ColType.BOOL,
    "TEXT": ColType.TEXT, "VARCHAR": ColType.TEXT, "CHAR": ColType.TEXT,
    "BLOB": ColType.BLOB,
}


# ── Serializer ────────────────────────────────────────────────────────────────

def encode_row(values: list, col_types: list[ColType]) -> bytes:
    """Encode a list of Python values into a row byte string."""
    ncols = len(col_types)
    null_bytes = math.ceil(ncols / 8)
    null_bitmap = bytearray(null_bytes)

    fixed_parts = []
    var_lengths  = []
    var_parts    = []

    for i, (val, ctype) in enumerate(zip(values, col_types)):
        if val is None:
            null_bitmap[i // 8] |= (1 << (i % 8))
            if ctype in FIXED_SIZES:
                fixed_parts.append(b"\x00" * FIXED_SIZES[ctype])
            else:
                var_lengths.append(0)
                # no var_part for NULL
        else:
            if ctype == ColType.INT:
                fixed_parts.append(FIXED_STRUCTS[ColType.INT].pack(int(val)))
            elif ctype == ColType.BIGINT:
                fixed_parts.append(FIXED_STRUCTS[ColType.BIGINT].pack(int(val)))
            elif ctype == ColType.FLOAT:
                fixed_parts.append(FIXED_STRUCTS[ColType.FLOAT].pack(float(val)))
            elif ctype == ColType.BOOL:
                fixed_parts.append(FIXED_STRUCTS[ColType.BOOL].pack(bool(val)))
            elif ctype == ColType.TEXT:
                encoded = str(val).encode("utf-8")
                var_lengths.append(len(encoded))
                var_parts.append(encoded)
            elif ctype == ColType.BLOB:
                raw = val if isinstance(val, (bytes, bytearray)) else str(val).encode()
                var_lengths.append(len(raw))
                var_parts.append(raw)

    parts = [bytes(null_bitmap)] + fixed_parts
    for vl in var_lengths:
        parts.append(VAR_LEN_STRUCT.pack(vl))
    parts += var_parts
    return b"".join(parts)


def decode_row(data: bytes, col_types: list[ColType]) -> list:
    """Decode a row byte string into a list of Python values."""
    ncols     = len(col_types)
    null_bytes = math.ceil(ncols / 8)
    null_bitmap = data[:null_bytes]
    pos = null_bytes

    def is_null(i):
        return bool(null_bitmap[i // 8] & (1 << (i % 8)))

    values    = []
    var_colsi = []

    for i, ctype in enumerate(col_types):
        if ctype in FIXED_SIZES:
            sz  = FIXED_SIZES[ctype]
            raw = data[pos: pos + sz]
            pos += sz
            if is_null(i):
                values.append(None)
            else:
                (v,) = FIXED_STRUCTS[ctype].unpack(raw)
                values.append(v)
        else:
            var_colsi.append(i)
            values.append(None)  # placeholder

    # read var lengths
    var_lengths = []
    for _ in var_colsi:
        (vl,) = VAR_LEN_STRUCT.unpack_from(data, pos)
        var_lengths.append(vl)
        pos += 2

    # read var data
    for idx, i in enumerate(var_colsi):
        vl = var_lengths[idx]
        if is_null(i) or vl == 0:
            values[i] = None
        else:
            raw = data[pos: pos + vl]
            pos += vl
            ctype = col_types[i]
            values[i] = raw.decode("utf-8") if ctype == ColType.TEXT else bytes(raw)

    return values
