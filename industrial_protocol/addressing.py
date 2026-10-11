"""Modbus address conversion with no hidden guessing."""

from .models import AddressMode, DataArea


class AddressError(ValueError):
    """Raised when a visible address cannot map to a protocol offset."""


def to_protocol_offset(address: int, mode: AddressMode, area: DataArea) -> int:
    """Convert the displayed address to the zero-based PDU offset.

    The mode is always supplied explicitly so 40001 is never silently treated
    as either a reference address or a raw protocol offset.
    """
    if address < 0:
        raise AddressError("地址不能为负数")

    if mode == AddressMode.RAW:
        offset = address
    elif mode == AddressMode.ONE_BASED:
        if address < 1:
            raise AddressError("One Based 地址必须从 1 开始")
        offset = address - 1
    elif mode == AddressMode.REFERENCE_3X:
        if area != DataArea.INPUT_REGISTERS:
            raise AddressError("3xxxx Reference 仅适用于 Input Registers / FC04")
        if not 30001 <= address <= 39999:
            raise AddressError("3xxxx Reference 地址范围应为 30001–39999")
        offset = address - 30001
    elif mode == AddressMode.REFERENCE_4X:
        if area != DataArea.HOLDING_REGISTERS:
            raise AddressError("4xxxx Reference 仅适用于 Holding Registers / FC03/06/16")
        if not 40001 <= address <= 49999:
            raise AddressError("4xxxx Reference 地址范围应为 40001–49999")
        offset = address - 40001
    else:
        raise AddressError("未知地址模式")

    if offset > 0xFFFF:
        raise AddressError("协议地址超出 0–65535")
    return offset

