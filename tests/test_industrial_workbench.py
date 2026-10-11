import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from server import app


class IndustrialWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_fullscreen_workbench_route_and_assets(self):
        response = self.client.get("/industrial")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data.count(b"data-node="), 5)
            self.assertIn(b"industrial-workbench.js", response.data)
            self.assertIn(b'id="iw-opc-workspace"', response.data)
            self.assertIn(b'id="opc-item-body"', response.data)
            self.assertIn(b"OPC UA Subscription", response.data)
            self.assertIn(b'<option value="real" selected>', response.data)
            self.assertIn(b'RTU over TCP', response.data)
            self.assertIn(b'id="iw-self-check"', response.data)
            self.assertIn(b'id="opc-browse"', response.data)
            self.assertIn(b"Publishing Interval (ms)", response.data)
            self.assertIn(b"MonitoredItem", response.data)
        finally:
            response.close()
        for asset in ("/static/css/industrial.css", "/static/js/industrial-workbench.js"):
            response = self.client.get(asset)
            try:
                self.assertEqual(response.status_code, 200)
                if asset.endswith("industrial-workbench.js"):
                    self.assertIn(b"UBInt32", response.data)
                    self.assertIn(b"property_407825926124554_value", response.data)
            finally:
                response.close()

    def test_dashboard_links_to_fullscreen_workbench(self):
        response = self.client.get("/")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'href="/industrial"', response.data)
        finally:
            response.close()

    def test_real_industrial_self_check_and_validation_api(self):
        response = self.client.get("/api/industrial/self-check")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json["ready"])
            self.assertTrue(response.json["dependencies"]["asyncua"]["installed"])
            self.assertTrue(response.json["dependencies"]["pymodbus"]["installed"])
        finally:
            response.close()
        response = self.client.post("/api/industrial/modbus/execute", json={"operation": "9"})
        try:
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json["category"], "Validation error")
        finally:
            response.close()

    def test_opc_runtime_status_api_is_available(self):
        response = self.client.get("/api/industrial/opc/status")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn("connected", response.json["result"])
            self.assertIn("items", response.json["result"])
        finally:
            response.close()

    def test_real_write_apis_are_blocked(self):
        response = self.client.post("/api/industrial/modbus/execute", json={"operation": "6"})
        try:
            self.assertEqual(response.status_code, 400)
            self.assertIn("只开放", response.json["error"])
        finally:
            response.close()
        response = self.client.post("/api/industrial/opc/write", json={"node_id": "ns=2;s=x", "value": 1})
        try:
            self.assertEqual(response.status_code, 403)
            self.assertIn("只读", response.json["error"])
        finally:
            response.close()


if __name__ == "__main__":
    unittest.main()
