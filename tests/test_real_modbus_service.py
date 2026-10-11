import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from industrial_protocol.modbus_service import RealModbusService


class _RegisterResponse:
    registers = [0xFFFF, 0xFFFE]

    @staticmethod
    def isError():
        return False


class _BitResponse:
    bits = [True, False, True]

    @staticmethod
    def isError():
        return False


class RealModbusServiceTests(unittest.TestCase):
    def test_rtu_over_tcp_uses_rtu_framer_and_pinned_slave_keyword(self):
        from pymodbus import Framer

        with patch("pymodbus.client.ModbusTcpClient") as client_class:
            client = client_class.return_value
            client.connect.return_value = True
            client.read_holding_registers.return_value = _RegisterResponse()
            result = RealModbusService().execute({
                "transport": "rtu_over_tcp",
                "host": "127.0.0.1",
                "port": 4002,
                "unit_id": 7,
                "operation": 3,
                "address_mode": "raw",
                "address": 82,
                "quantity": 2,
                "data_type": "int32",
                "byte_order": "ABCD",
                "timeout": 1,
                "retries": 0,
            })

        self.assertEqual(result["decoded_value"], -2)
        self.assertIn("RTU over TCP", result["transport"])
        self.assertEqual(client_class.call_args.kwargs["framer"], Framer.RTU)
        client.read_holding_registers.assert_called_once_with(82, count=2, slave=7)

    def test_fc01_returns_requested_bits(self):
        with patch("pymodbus.client.ModbusTcpClient") as client_class:
            client = client_class.return_value
            client.connect.return_value = True
            client.read_coils.return_value = _BitResponse()
            result = RealModbusService().execute({
                "transport": "modbus_tcp",
                "host": "127.0.0.1",
                "port": 502,
                "unit_id": 1,
                "operation": 1,
                "address_mode": "raw",
                "address": 0,
                "quantity": 3,
            })

        self.assertEqual(result["decoded_value"], [True, False, True])
        client.read_coils.assert_called_once_with(0, count=3, slave=1)

    def test_live_writes_are_rejected_before_connection(self):
        with self.assertRaisesRegex(ValueError, "只开放"):
            RealModbusService().execute({"operation": 16})


if __name__ == "__main__":
    unittest.main()
