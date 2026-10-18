import tempfile
import time
import unittest
from pathlib import Path

from gateway.app import create_app
from gateway.config import Config
from gateway.simulator import Simulator


class DisplayDeviceTelemetryTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.config = Config(
            data_dir=Path(self.temp.name),
            admin_token="a" * 64,
            device_key="b" * 64,
            mode="simulator",
            device_host="127.0.0.1",
        )

        self.app = create_app(
            self.config,
            transport=Simulator(),
        )

        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.state = self.app.extensions["workflow"]


    def tearDown(self):
        self.app.extensions["ledger"].db.close()


    def test_initial_state_is_unknown_and_does_not_claim_device_state(self):
        response = self.client.get("/api/display/devices")

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.json,
            {
                "cam": {
                    "reachable": None,
                    "authenticated": None,
                    "fresh": False,
                    "state": None,
                    "led_reported": None,
                    "gpio_enabled": None,
                    "age_ms": None,
                },
                "car": {
                    "reachable": None,
                    "authenticated": None,
                    "fresh": False,
                    "state": None,
                    "last_action": None,
                    "motor_a_active": None,
                    "motor_b_active": None,
                    "ldr32": None,
                    "ldr33": None,
                    "camera_ready": None,
                    "camera_active": False,
                    "rssi_dbm": None,
                    "age_ms": None,
                    "status_rtt": {
                        "state": "UNAVAILABLE",
                        "ms": None,
                        "age_ms": None,
                    },
                },
            },
        )


    def test_fresh_authenticated_led_on_report_is_exposed(self):
        self.state["cam_report"] = {
            "state": "RUNNING",
            "led_reported": 1,
            "gpio_enabled": 1,
            "origin": "DEVICE",
            "updated": time.monotonic(),
        }

        response = self.client.get("/api/display/devices")

        self.assertEqual(response.status_code, 200)

        cam = response.json["cam"]

        self.assertTrue(cam["reachable"])
        self.assertTrue(cam["authenticated"])
        self.assertTrue(cam["fresh"])
        self.assertEqual(cam["state"], "RUNNING")
        self.assertEqual(cam["led_reported"], 1)
        self.assertEqual(cam["gpio_enabled"], 1)

        self.assertIsInstance(cam["age_ms"], int)
        self.assertGreaterEqual(cam["age_ms"], 0)
        self.assertLessEqual(cam["age_ms"], 8000)


    def test_fresh_authenticated_led_off_report_is_exposed(self):
        self.state["cam_report"] = {
            "state": "STOPPED",
            "led_reported": 0,
            "gpio_enabled": 1,
            "origin": "DEVICE",
            "updated": time.monotonic(),
        }

        response = self.client.get("/api/display/devices")

        self.assertEqual(response.status_code, 200)

        cam = response.json["cam"]

        self.assertTrue(cam["reachable"])
        self.assertTrue(cam["authenticated"])
        self.assertTrue(cam["fresh"])
        self.assertEqual(cam["state"], "STOPPED")
        self.assertEqual(cam["led_reported"], 0)
        self.assertEqual(cam["gpio_enabled"], 1)


    def test_stale_report_does_not_claim_current_led_state(self):
        self.state["cam_report"] = {
            "state": "RUNNING",
            "led_reported": 1,
            "gpio_enabled": 1,
            "origin": "DEVICE",
            "updated": time.monotonic() - 9.0,
        }

        response = self.client.get("/api/display/devices")

        self.assertEqual(response.status_code, 200)

        cam = response.json["cam"]

        self.assertIsNone(cam["reachable"])
        self.assertIsNone(cam["authenticated"])
        self.assertFalse(cam["fresh"])
        self.assertIsNone(cam["state"])
        self.assertIsNone(cam["led_reported"])
        self.assertIsNone(cam["gpio_enabled"])

        self.assertIsInstance(cam["age_ms"], int)
        self.assertGreater(cam["age_ms"], 8000)


    def test_known_transport_failure_reports_unreachable(self):
        self.state["cam_health"] = "UNAVAILABLE"
        self.state["cam_report"] = None

        response = self.client.get("/api/display/devices")

        self.assertEqual(response.status_code, 200)

        cam = response.json["cam"]

        self.assertFalse(cam["reachable"])
        self.assertFalse(cam["authenticated"])
        self.assertFalse(cam["fresh"])
        self.assertIsNone(cam["state"])
        self.assertIsNone(cam["led_reported"])
        self.assertIsNone(cam["gpio_enabled"])
        self.assertIsNone(cam["age_ms"])


    def test_display_telemetry_read_does_not_query_transport(self):
        transport = self.app.extensions["transport"]

        def forbidden():
            raise AssertionError(
                "Display telemetry must not query the device transport."
            )

        transport.status = forbidden

        response = self.client.get("/api/display/devices")

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
