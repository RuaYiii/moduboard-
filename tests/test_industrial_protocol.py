import math
import struct
import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from industrial_protocol.addressing import AddressError, to_protocol_offset
from industrial_protocol.decoder import DecodeError, decode_hex
from industrial_protocol.models import AddressMode, ByteOrder, DataArea, DataType, DecodeConfig
from modules import industrial_debugger
from modules import industrial_decoder


class AddressingTests(unittest.TestCase):
    def test_reference_40001_maps_to_holding_offset_zero(self):
        self.assertEqual(
            to_protocol_offset(40001, AddressMode.REFERENCE_4X, DataArea.HOLDING_REGISTERS),
            0,
        )

    def test_reference_30001_maps_to_input_offset_zero(self):
        self.assertEqual(
            to_protocol_offset(30001, AddressMode.REFERENCE_3X, DataArea.INPUT_REGISTERS),
            0,
        )

    def test_reference_mode_rejects_wrong_data_area(self):
        with self.assertRaises(AddressError):
            to_protocol_offset(40001, AddressMode.REFERENCE_4X, DataArea.INPUT_REGISTERS)

    def test_one_based_address_is_explicit(self):
        self.assertEqual(to_protocol_offset(1, AddressMode.ONE_BASED, DataArea.COILS), 0)


class DecoderTests(unittest.TestCase):
    def decode(self, raw, data_type, order=ByteOrder.ABCD, **kwargs):
        return decode_hex(raw, DecodeConfig(data_type=data_type, byte_order=order, **kwargs))

    def test_uint16_and_int16(self):
        self.assertEqual(self.decode("FF FF", DataType.UINT16), 65535)
        self.assertEqual(self.decode("FF FF", DataType.INT16), -1)

    def test_float32_all_orders(self):
        expected = 220.0
        samples = {
            ByteOrder.ABCD: "43 5C 00 00",
            ByteOrder.BADC: "5C 43 00 00",
            ByteOrder.CDAB: "00 00 43 5C",
            ByteOrder.DCBA: "00 00 5C 43",
        }
        for order, raw in samples.items():
            with self.subTest(order=order):
                self.assertTrue(math.isclose(self.decode(raw, DataType.FLOAT32, order), expected))

    def test_int32_uint32_and_float64(self):
        self.assertEqual(self.decode("FF FF FF FF", DataType.INT32), -1)
        self.assertEqual(self.decode("FF FF FF FF", DataType.UINT32), 4294967295)
        encoded = " ".join("%02X" % byte for byte in struct.pack(">d", 238.5))
        self.assertEqual(self.decode(encoded, DataType.FLOAT64), 238.5)

    def test_int64_and_uint64(self):
        self.assertEqual(self.decode("FF FF FF FF FF FF FF FF", DataType.INT64), -1)
        self.assertEqual(
            self.decode("FF FF FF FF FF FF FF FF", DataType.UINT64),
            18446744073709551615,
        )

    def test_bit_bitfield_scale_offset_and_string(self):
        self.assertTrue(self.decode("00 09", DataType.BIT, bit_index=3))
        field = self.decode("00 09", DataType.BITFIELD)
        self.assertEqual(field["set_bits"], [0, 3])
        self.assertEqual(self.decode("00 64", DataType.UINT16, scale=0.1, offset=2), 12)
        self.assertEqual(self.decode("48 69 00 00", DataType.STRING), "Hi")

    def test_invalid_hex_is_structured_error(self):
        with self.assertRaises(DecodeError):
            self.decode("ZZ 00", DataType.UINT16)


class DebuggerModuleTests(unittest.TestCase):
    def test_render_contains_cascade_and_safe_simulator(self):
        result = industrial_debugger.render({}, {})
        self.assertIn('data-input="protocol_family"', result["html"])
        self.assertIn('data-input="transport"', result["html"])
        self.assertIn('data-input="operation"', result["html"])
        self.assertIn("当前不会访问真实设备", result["html"])
        self.assertIn("var(--color-surface)", result["html"])
        self.assertNotIn("background:#0a0f17", result["html"])
        self.assertIn("Unit ID", result["html"])
        self.assertIn("FC03 Read Holding Registers", result["html"])
        self.assertIn(">Float32</option>", result["html"])

    def test_default_execute_exposes_reference_and_protocol_offset(self):
        rendered = industrial_debugger.render({}, {})
        result = industrial_debugger.on_action("execute", {}, {}, rendered["state"])
        value = result["state"]["result"]
        self.assertEqual(value["value"], "220")
        self.assertIn("协议偏移 0", value["meta"])
        self.assertEqual(value["raw"], "00 00 43 5C")

    def test_bad_reference_mode_becomes_visible_structured_error(self):
        state = industrial_debugger.render({}, {})["state"]
        payload = {"operation": "4", "address_mode": "reference_4x", "address": "40001"}
        result = industrial_debugger.on_action("execute", payload, {}, state)
        self.assertFalse(result["state"]["result"]["ok"])
        self.assertIn("4xxxx Reference", result["state"]["result"]["value"])

    def test_decoder_is_a_separate_theme_aware_module(self):
        rendered = industrial_decoder.render({}, {})
        self.assertIn("仅解释数据", rendered["html"])
        self.assertIn("var(--color-text-primary)", rendered["html"])
        result = industrial_decoder.on_action("decode", {}, {}, rendered["state"])
        self.assertEqual(result["state"]["result"]["value"], "220")

    def test_opc_ua_form_uses_native_concepts(self):
        rendered = industrial_debugger.render({}, {})
        for label in (
            "Endpoint URL", "Security Mode", "Security Policy", "Authentication",
            "NodeId", "Publishing Interval (ms)", "Sampling Interval (ms)", "Queue Size",
        ):
            self.assertIn(label, rendered["html"])
        result = industrial_debugger.on_action(
            "execute",
            {"protocol_family": "opc", "transport": "opc_ua", "operation": "subscribe"},
            {},
            rendered["state"],
        )
        self.assertEqual(result["state"]["result"]["title"], "Subscription #1")
        self.assertIn("MonitoredItem", result["state"]["result"]["value"])

    def test_opc_subscription_accepts_multiple_monitored_items(self):
        state = industrial_debugger.render({}, {})["state"]
        items = [
            {"node_id": "ns=2;s=BMS.Power.VoltageA", "sampling_interval": "500", "queue_size": "10", "deadband": "0.1"},
            {"node_id": "ns=2;s=BMS.Room.Temperature", "sampling_interval": "1000", "queue_size": "5", "deadband": "0"},
            {"node_id": "ns=2;s=BMS.Room.WaterLeak", "sampling_interval": "250", "queue_size": "20", "deadband": "0"},
        ]
        result = industrial_debugger.on_action(
            "execute",
            {
                "protocol_family": "opc", "transport": "opc_ua", "operation": "subscribe",
                "subscription_name": "Critical Operations", "monitored_items": items,
            },
            {}, state,
        )
        self.assertTrue(result["state"]["result"]["ok"])
        self.assertIn("3 MonitoredItems", result["state"]["result"]["value"])
        self.assertEqual(len(result["state"]["monitored_items"]), 3)
        self.assertIn("3 items", result["state"]["logs"][-1]["text"])

    def test_opc_subscription_lifetime_respects_keepalive_ratio(self):
        state = industrial_debugger.render({}, {})["state"]
        result = industrial_debugger.on_action(
            "execute",
            {
                "protocol_family": "opc", "transport": "opc_ua", "operation": "subscribe",
                "keep_alive_count": "10", "lifetime_count": "20",
                "monitored_items": [{"node_id": "ns=2;s=BMS.Power.VoltageA", "sampling_interval": "500", "queue_size": "10"}],
            },
            {}, state,
        )
        self.assertFalse(result["state"]["result"]["ok"])
        self.assertIn("至少为 KeepAlive Count 的 3 倍", result["state"]["result"]["value"])

    def test_single_write_and_coil_type_constraints_are_enforced(self):
        state = industrial_debugger.render({}, {})["state"]
        bad_quantity = industrial_debugger.on_action(
            "execute",
            {"operation": "6", "quantity": "2", "data_type": "uint16"},
            {}, state,
        )
        self.assertFalse(bad_quantity["state"]["result"]["ok"])
        self.assertIn("Quantity 必须为 1", bad_quantity["state"]["result"]["value"])
        bad_type = industrial_debugger.on_action(
            "execute",
            {"operation": "1", "quantity": "1", "data_type": "float32", "address_mode": "raw", "address": "0"},
            {}, state,
        )
        self.assertFalse(bad_type["state"]["result"]["ok"])
        self.assertIn("仅支持 Bool", bad_type["state"]["result"]["value"])

    def test_opc_security_combinations_are_validated(self):
        state = industrial_debugger.render({}, {})["state"]
        result = industrial_debugger.on_action(
            "execute",
            {"protocol_family": "opc", "transport": "opc_ua", "operation": "connect", "security_mode": "None", "security_policy": "Basic256Sha256"},
            {}, state,
        )
        self.assertFalse(result["state"]["result"]["ok"])
        self.assertIn("Security Policy 必须为 None", result["state"]["result"]["value"])

    def test_no_template_placeholders_leak_into_rendered_html(self):
        for module in (industrial_debugger, industrial_decoder):
            rendered = module.render({}, {})["html"]
            self.assertNotIn("__DATA_TYPE__", rendered)
            self.assertNotIn("__OPC_TYPES__", rendered)


if __name__ == "__main__":
    unittest.main()
