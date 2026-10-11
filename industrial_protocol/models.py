"""Explicit domain models for the industrial protocol debugger template."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class Transport(str, Enum):
    MODBUS_TCP = "modbus_tcp"
    RTU_OVER_TCP = "rtu_over_tcp"
    MODBUS_RTU = "modbus_rtu"
    OPC_UA = "opc_ua"
    OPC_DA = "opc_da"


class DataArea(str, Enum):
    COILS = "coils"
    DISCRETE_INPUTS = "discrete_inputs"
    HOLDING_REGISTERS = "holding_registers"
    INPUT_REGISTERS = "input_registers"


class AddressMode(str, Enum):
    RAW = "raw"
    ONE_BASED = "one_based"
    REFERENCE_3X = "reference_3x"
    REFERENCE_4X = "reference_4x"


class DataType(str, Enum):
    BOOL = "bool"
    BIT = "bit"
    BITFIELD = "bitfield"
    UINT16 = "uint16"
    INT16 = "int16"
    UINT32 = "uint32"
    INT32 = "int32"
    FLOAT32 = "float32"
    UINT64 = "uint64"
    INT64 = "int64"
    FLOAT64 = "float64"
    STRING = "string"
    HEX = "hex"


class ByteOrder(str, Enum):
    ABCD = "ABCD"
    BADC = "BADC"
    CDAB = "CDAB"
    DCBA = "DCBA"


FUNCTION_AREAS = {
    1: DataArea.COILS,
    2: DataArea.DISCRETE_INPUTS,
    3: DataArea.HOLDING_REGISTERS,
    4: DataArea.INPUT_REGISTERS,
    5: DataArea.COILS,
    6: DataArea.HOLDING_REGISTERS,
    15: DataArea.COILS,
    16: DataArea.HOLDING_REGISTERS,
}


@dataclass(frozen=True)
class DecodeConfig:
    data_type: DataType = DataType.FLOAT32
    byte_order: ByteOrder = ByteOrder.ABCD
    bit_index: Optional[int] = None
    scale: float = 1.0
    offset: float = 0.0
    encoding: str = "utf-8"


@dataclass(frozen=True)
class ModbusRequest:
    transport: Transport
    unit_id: int
    function_code: int
    address: int
    quantity: int = 1
    timeout_seconds: float = 2.0
    retries: int = 0

    @property
    def data_area(self) -> DataArea:
        return FUNCTION_AREAS[self.function_code]


@dataclass
class ModbusResult:
    request: ModbusRequest
    raw_bytes: bytes = b""
    raw_registers: List[int] = field(default_factory=list)
    raw_bits: List[bool] = field(default_factory=list)
    decoded_value: Any = None
    latency_ms: float = 0.0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    )
    error: Optional[Dict[str, str]] = None
