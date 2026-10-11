"""Protocol-independent raw byte decoder for Modbus register data."""

import re
import struct
from typing import Any

from .models import ByteOrder, DataType, DecodeConfig


class DecodeError(ValueError):
    """Raised when raw input and decode configuration are incompatible."""


_HEX_TOKEN = re.compile(r"^[0-9a-fA-F]{2}$")


def parse_hex_bytes(value: str) -> bytes:
    cleaned = value.replace("0x", "").replace("0X", "")
    tokens = [token for token in re.split(r"[\s,;:_-]+", cleaned.strip()) if token]
    if len(tokens) == 1 and len(tokens[0]) > 2:
        compact = tokens[0]
        if len(compact) % 2:
            raise DecodeError("HEX 字节数必须为偶数")
        tokens = [compact[index:index + 2] for index in range(0, len(compact), 2)]
    if not tokens or any(not _HEX_TOKEN.match(token) for token in tokens):
        raise DecodeError("请输入类似 00 00 43 5C 的十六进制字节")
    return bytes(int(token, 16) for token in tokens)


def _reorder(raw: bytes, order: ByteOrder) -> bytes:
    if order == ByteOrder.ABCD or len(raw) < 2:
        return raw
    words = [raw[index:index + 2] for index in range(0, len(raw), 2)]
    if any(len(word) != 2 for word in words):
        raise DecodeError("寄存器数据必须由完整的 2 字节组成")
    if order == ByteOrder.BADC:
        return b"".join(word[::-1] for word in words)
    if order == ByteOrder.CDAB:
        return b"".join(reversed(words))
    if order == ByteOrder.DCBA:
        return raw[::-1]
    raise DecodeError("未知字节序")


def _require(raw: bytes, size: int, name: str) -> bytes:
    if len(raw) < size:
        raise DecodeError("%s 至少需要 %s 字节，当前只有 %s 字节" % (name, size, len(raw)))
    return raw[:size]


def decode_bytes(raw: bytes, config: DecodeConfig) -> Any:
    data_type = config.data_type
    if data_type == DataType.HEX:
        return " ".join("%02X" % byte for byte in raw)
    if data_type == DataType.STRING:
        try:
            return _reorder(raw, config.byte_order).rstrip(b"\x00").decode(config.encoding)
        except UnicodeDecodeError as exc:
            raise DecodeError("字符串无法按 %s 解码" % config.encoding) from exc

    size_map = {
        DataType.BOOL: 2,
        DataType.BIT: 2,
        DataType.BITFIELD: 2,
        DataType.UINT16: 2,
        DataType.INT16: 2,
        DataType.UINT32: 4,
        DataType.INT32: 4,
        DataType.FLOAT32: 4,
        DataType.UINT64: 8,
        DataType.INT64: 8,
        DataType.FLOAT64: 8,
    }
    ordered = _reorder(_require(raw, size_map[data_type], data_type.value), config.byte_order)
    formats = {
        DataType.UINT16: ">H",
        DataType.INT16: ">h",
        DataType.UINT32: ">I",
        DataType.INT32: ">i",
        DataType.FLOAT32: ">f",
        DataType.UINT64: ">Q",
        DataType.INT64: ">q",
        DataType.FLOAT64: ">d",
    }
    unsigned = int.from_bytes(ordered, byteorder="big", signed=False)
    if data_type == DataType.BOOL:
        value = bool(unsigned)
    elif data_type == DataType.BIT:
        bit_index = 0 if config.bit_index is None else config.bit_index
        if not 0 <= bit_index <= 15:
            raise DecodeError("Bit Index 必须在 0–15")
        value = bool((unsigned >> bit_index) & 1)
    elif data_type == DataType.BITFIELD:
        value = {
            "decimal": unsigned,
            "binary": format(unsigned, "016b"),
            "set_bits": [index for index in range(16) if unsigned & (1 << index)],
        }
    else:
        value = struct.unpack(formats[data_type], ordered)[0]

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Preserve exact 64-bit integers when no engineering conversion is
        # requested. Casting UInt64 to float here silently loses low bits.
        if config.scale != 1.0 or config.offset != 0.0:
            value = value * config.scale + config.offset
    return value


def decode_hex(value: str, config: DecodeConfig) -> Any:
    return decode_bytes(parse_hex_bytes(value), config)
