"""Application service and replaceable backend boundary.

The first slice ships with a deterministic simulator. A future pymodbus or OPC
UA SDK adapter implements the same backend methods without coupling SDK calls
to the UI module.
"""

from abc import ABC, abstractmethod
from time import perf_counter

from .decoder import decode_bytes
from .models import DataType, DecodeConfig, ModbusRequest, ModbusResult


class ModbusBackend(ABC):
    @abstractmethod
    def execute(self, request: ModbusRequest, decode: DecodeConfig, raw_bytes: bytes) -> ModbusResult:
        raise NotImplementedError


class SimulatorBackend(ModbusBackend):
    """Safe backend for UI development and point-table verification."""

    def execute(self, request: ModbusRequest, decode: DecodeConfig, raw_bytes: bytes) -> ModbusResult:
        started = perf_counter()
        result = ModbusResult(request=request, raw_bytes=raw_bytes)
        if request.function_code in (1, 2, 5, 15):
            result.raw_bits = [bool((byte >> bit) & 1) for byte in raw_bytes for bit in range(8)]
            result.decoded_value = result.raw_bits[:request.quantity]
        else:
            result.raw_registers = [
                int.from_bytes(raw_bytes[index:index + 2], "big")
                for index in range(0, len(raw_bytes) - 1, 2)
            ]
            result.decoded_value = decode_bytes(raw_bytes, decode)
        result.latency_ms = round((perf_counter() - started) * 1000 + 3.2, 2)
        return result

