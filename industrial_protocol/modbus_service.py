"""Real Modbus TCP/RTU application service backed by PyModbus.

The UI sends an explicit address mode and function code. This service owns
transport I/O, protocol limits, exception mapping, PDU logging, and decoding.
"""

from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Dict, Iterable, List

from .addressing import to_protocol_offset
from .decoder import decode_bytes
from .models import AddressMode, ByteOrder, DataType, DecodeConfig, FUNCTION_AREAS


EXCEPTION_NAMES = {
    1: "Illegal Function",
    2: "Illegal Data Address",
    3: "Illegal Data Value",
    4: "Slave Device Failure",
    5: "Acknowledge",
    6: "Slave Device Busy",
    8: "Memory Parity Error",
    10: "Gateway Path Unavailable",
    11: "Gateway Target Device Failed to Respond",
}


class IndustrialCommunicationError(RuntimeError):
    """A structured, user-facing transport or protocol failure."""

    def __init__(self, category: str, message: str, details: str = "") -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.details = details


def _integer(value: Any, label: str, low: int, high: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是整数") from exc
    if not low <= parsed <= high:
        raise ValueError(f"{label} 必须在 {low}～{high} 之间")
    return parsed


def _float(value: Any, label: str, low: float, high: float) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是数字") from exc
    if not low <= parsed <= high:
        raise ValueError(f"{label} 必须在 {low}～{high} 之间")
    return parsed


def _hex(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)


def _u16(value: int) -> bytes:
    return value.to_bytes(2, "big")


def _pack_bits(values: Iterable[bool]) -> bytes:
    bits = list(values)
    packed = bytearray((len(bits) + 7) // 8)
    for index, enabled in enumerate(bits):
        if enabled:
            packed[index // 8] |= 1 << (index % 8)
    return bytes(packed)


def _parse_bool(value: Any) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "on", "yes", "closed"}:
        return True
    if normalized in {"0", "false", "off", "no", "open"}:
        return False
    raise ValueError("Coil Value 请输入 true/false、1/0 或 on/off")


def _split_values(value: Any) -> List[str]:
    text = str(value or "").replace(";", ",").replace("\n", ",")
    return [item.strip() for item in text.split(",") if item.strip()]


def _validate_quantity(function_code: int, quantity: int) -> None:
    limits = {1: 2000, 2: 2000, 3: 125, 4: 125}
    if function_code not in limits:
        raise ValueError("真实设备模式只开放 FC01/02/03/04 读取")
    if not 1 <= quantity <= limits[function_code]:
        raise ValueError(f"FC{function_code:02X} Quantity 必须在 1～{limits[function_code]} 之间")


def _build_request_pdu(function_code: int, address: int, quantity: int, values: List[Any]) -> bytes:
    if function_code in (1, 2, 3, 4):
        return bytes([function_code]) + _u16(address) + _u16(quantity)
    if function_code == 5:
        return bytes([function_code]) + _u16(address) + (b"\xFF\x00" if values[0] else b"\x00\x00")
    if function_code == 6:
        return bytes([function_code]) + _u16(address) + _u16(values[0])
    if function_code == 15:
        packed = _pack_bits(values)
        return bytes([function_code]) + _u16(address) + _u16(quantity) + bytes([len(packed)]) + packed
    raw = b"".join(_u16(value) for value in values)
    return bytes([function_code]) + _u16(address) + _u16(quantity) + bytes([len(raw)]) + raw


def _response_pdu(function_code: int, response: Any, quantity: int) -> bytes:
    if getattr(response, "isError", lambda: False)():
        return bytes([function_code | 0x80, int(getattr(response, "exception_code", 0))])
    if function_code in (1, 2):
        packed = _pack_bits(list(response.bits)[:quantity])
        return bytes([function_code, len(packed)]) + packed
    if function_code in (3, 4):
        raw = b"".join(_u16(register) for register in response.registers)
        return bytes([function_code, len(raw)]) + raw
    if function_code in (5, 6):
        return bytes([function_code]) + _u16(int(response.address)) + _u16(int(response.value))
    return bytes([function_code]) + _u16(int(response.address)) + _u16(int(response.count))


def _classify_exception(exc: Exception) -> IndustrialCommunicationError:
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()
    if "timed out" in lowered or "timeout" in lowered or "no response" in lowered:
        category = "TCP timeout" if "serial" not in lowered else "Serial timeout"
    elif "refused" in lowered:
        category = "Connection refused"
    elif "reset" in lowered:
        category = "Connection reset"
    elif "crc" in lowered:
        category = "CRC error"
    elif "incomplete" in lowered or "short" in lowered:
        category = "Incomplete frame"
    else:
        category = "Communication error"
    return IndustrialCommunicationError(category, text, exc.__class__.__name__)


class RealModbusService:
    """Execute one transparent Modbus request against a real device."""

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from pymodbus import Framer
            from pymodbus.client import ModbusSerialClient, ModbusTcpClient
            from pymodbus.exceptions import ModbusException
        except ImportError as exc:
            raise IndustrialCommunicationError("Dependency missing", "未安装 pymodbus / pyserial，请先运行离线安装脚本") from exc

        function_code = _integer(payload.get("operation"), "Function Code", 1, 16)
        if function_code not in (1, 2, 3, 4):
            raise ValueError("真实设备模式只开放 FC01/02/03/04 读取；写入可在离线模拟中演练")
        unit_id = _integer(payload.get("unit_id", 1), "Unit ID", 0, 247)
        visible_address = _integer(payload.get("address", 0), "Address", 0, 65535)
        address = to_protocol_offset(visible_address, AddressMode(payload.get("address_mode", "raw")), FUNCTION_AREAS[function_code])
        quantity = _integer(payload.get("quantity", 1), "Quantity", 1, 2000)
        _validate_quantity(function_code, quantity)
        timeout = _float(payload.get("timeout", 3), "Timeout", 0.1, 60)
        retries = _integer(payload.get("retries", 0), "Retries", 0, 5)
        transport = str(payload.get("transport", "modbus_tcp"))
        values: List[Any] = []

        if transport == "modbus_tcp":
            host = str(payload.get("host", "")).strip()
            if not host:
                raise ValueError("Host / IP 不能为空")
            port = _integer(payload.get("port", 502), "Port", 1, 65535)
            client = ModbusTcpClient(host, framer=Framer.SOCKET, port=port, timeout=timeout, retries=retries)
            transport_label = f"Modbus TCP {host}:{port}"
        elif transport == "rtu_over_tcp":
            host = str(payload.get("host", "")).strip()
            if not host:
                raise ValueError("Host / IP 不能为空")
            port = _integer(payload.get("port", 4001), "Port", 1, 65535)
            client = ModbusTcpClient(host, framer=Framer.RTU, port=port, timeout=timeout, retries=retries)
            transport_label = f"RTU over TCP {host}:{port}"
        elif transport == "modbus_rtu":
            serial_port = str(payload.get("serial_port", "")).strip()
            if not serial_port:
                raise ValueError("Serial Port 不能为空")
            client = ModbusSerialClient(
                port=serial_port,
                baudrate=_integer(payload.get("baud_rate", 9600), "Baud Rate", 300, 4000000),
                bytesize=_integer(payload.get("bytesize", 8), "Data Bits", 5, 8),
                parity=str(payload.get("parity", "N")),
                stopbits=_integer(payload.get("stopbits", 1), "Stop Bits", 1, 2),
                timeout=timeout,
                retries=retries,
            )
            transport_label = f"Modbus RTU {serial_port}"
        else:
            raise ValueError("真实通信支持 modbus_tcp / rtu_over_tcp / modbus_rtu")

        request_pdu = _build_request_pdu(function_code, address, quantity, values)
        started = perf_counter()
        try:
            if not client.connect():
                raise IndustrialCommunicationError("Connection failed", f"无法连接 {transport_label}")
            if function_code == 1:
                response = client.read_coils(address, count=quantity, slave=unit_id)
            elif function_code == 2:
                response = client.read_discrete_inputs(address, count=quantity, slave=unit_id)
            elif function_code == 3:
                response = client.read_holding_registers(address, count=quantity, slave=unit_id)
            elif function_code == 4:
                response = client.read_input_registers(address, count=quantity, slave=unit_id)
        except IndustrialCommunicationError:
            raise
        except (ModbusException, OSError) as exc:
            raise _classify_exception(exc) from exc
        finally:
            client.close()

        latency_ms = round((perf_counter() - started) * 1000, 2)
        response_pdu = _response_pdu(function_code, response, quantity)
        if response.isError():
            code = int(getattr(response, "exception_code", 0))
            name = EXCEPTION_NAMES.get(code, "Unknown Modbus Exception")
            raise IndustrialCommunicationError("Modbus exception", f"Modbus Exception {code:02X} · {name}", _hex(response_pdu))

        if function_code in (1, 2):
            bits = list(response.bits)[:quantity]
            raw_bytes = _pack_bits(bits)
            decoded_value: Any = bits[0] if quantity == 1 else bits
            raw_registers: List[int] = []
        elif function_code in (3, 4):
            raw_registers = list(response.registers)
            raw_bytes = b"".join(_u16(register) for register in raw_registers)
            config = DecodeConfig(
                data_type=DataType(payload.get("data_type", "hex")),
                byte_order=ByteOrder(payload.get("byte_order", "ABCD")),
                bit_index=int(payload["bit_index"]) if str(payload.get("bit_index", "")).strip() else None,
                scale=float(payload.get("scale", 1) or 1),
                offset=float(payload.get("decode_offset", 0) or 0),
                encoding=str(payload.get("encoding", "utf-8")),
            )
            decoded_value = decode_bytes(raw_bytes, config)
        return {
            "ok": True,
            "transport": transport_label,
            "unit_id": unit_id,
            "function_code": function_code,
            "visible_address": visible_address,
            "protocol_offset": address,
            "quantity": quantity,
            "decoded_value": decoded_value,
            "raw_registers": raw_registers,
            "raw_bytes": _hex(raw_bytes),
            "request_pdu": _hex(request_pdu),
            "response_pdu": _hex(response_pdu),
            "latency_ms": latency_ms,
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"),
        }


real_modbus_service = RealModbusService()
