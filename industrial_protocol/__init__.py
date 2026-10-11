"""Industrial protocol domain primitives used by ModuBoard modules."""

from .addressing import AddressError, to_protocol_offset
from .decoder import DecodeError, decode_hex, parse_hex_bytes
from .models import (
    AddressMode,
    ByteOrder,
    DataArea,
    DataType,
    DecodeConfig,
    ModbusRequest,
    ModbusResult,
    Transport,
)

__all__ = [
    "AddressError",
    "AddressMode",
    "ByteOrder",
    "DataArea",
    "DataType",
    "DecodeConfig",
    "DecodeError",
    "ModbusRequest",
    "ModbusResult",
    "Transport",
    "decode_hex",
    "parse_hex_bytes",
    "to_protocol_offset",
]
