import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gateway.app import create_app
from gateway.config import Config
from gateway.simulator import Simulator
from gateway.transport import HTTPTransport, TransportError


class WorkstationLedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(
            data_dir=Path(self.tmp.name),
            admin_token="2" * 64,
            device_key="3" * 64,
            mode="simulator",
        )
        self.sim = Simulator()
        self.app = create_app(self.cfg, self.sim)
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.extensions["ledger"].db.close()
        self.tmp.cleanup()

    def post(self, action, **headers):
        base = {"Origin": "http://localhost"}
        base.update(headers)
        return self.client.post(
            "/api/experiments/led/control",
            json={"action": action},
            headers=base
        )

    def test_origin_required(self):
        response = self.client.post(
            "/api/experiments/led/control",
            json={"action": "OFF"}
        )
        self.assertEqual(response.status_code, 403)

    def test_cross_site_rejected(self):
        response = self.post(
            "OFF",
            **{"Sec-Fetch-Site": "cross-site"}
        )
        self.assertEqual(response.status_code, 403)

    def test_on_refused_while_gateway_locked(self):
        with patch.object(self.sim, "command") as send:
            response = self.post("ON")
        self.assertEqual(response.status_code, 409)
        send.assert_not_called()

    def test_on_runs_fixed_bounded_program(self):
        self.app.extensions["workflow"]["locked"] = False

        response = self.post("ON")

        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["action"], "ON")
        self.assertEqual(response.json["reported"]["origin"], "SIMULATOR")
        self.assertEqual(response.json["reported"]["led_reported"], 1)

        rid = response.json["run_id"]
        run = self.app.extensions["ledger"].run(rid)
        self.assertEqual(run["program"], "L1,W1000,W1000,W1000,W1000,W1000,L0")

    def test_off_forces_stop_even_while_locked(self):
        self.app.extensions["workflow"]["locked"] = False
        on = self.post("ON")
        self.assertEqual(on.status_code, 200, on.json)

        self.app.extensions["workflow"]["locked"] = True
        off = self.post("OFF")

        self.assertEqual(off.status_code, 200, off.json)
        self.assertEqual(off.json["action"], "OFF")
        self.assertEqual(off.json["reported"]["state"], "STOPPED")
        self.assertEqual(off.json["reported"]["led_reported"], 0)


    def test_second_on_returns_device_busy_without_locking_gateway(self):
        self.app.extensions["workflow"]["locked"] = False

        first = self.post("ON")
        self.assertEqual(first.status_code, 200, first.json)

        second = self.post("ON")

        self.assertEqual(second.status_code, 409, second.json)
        self.assertEqual(second.json["error"], "DEVICE_BUSY")
        self.assertFalse(self.app.extensions["workflow"]["locked"])
        self.assertEqual(self.sim.state, "RUNNING")

    def test_post_timeout_status_confirms_led_off(self):
        self.app.extensions["workflow"]["locked"] = False

        on = self.post("ON")
        self.assertEqual(on.status_code, 200, on.json)

        rid = on.json["run_id"]

        self.sim.started -= 6.0

        status = self.client.post(
            "/api/experiments/led/status",
            json={"run_id": rid},
            headers={"Origin": "http://localhost"},
        )

        self.assertEqual(status.status_code, 200, status.json)
        self.assertTrue(status.json["current_device_run"])
        self.assertEqual(status.json["reported"]["led_reported"], 0)
        self.assertIn(
            status.json["reported"]["state"],
            ("COMPLETE", "STOPPED", "IDLE"),
        )
        self.assertEqual(
            status.json["state"],
            "DEVICE_REPORTED_COMPLETE",
        )

    def test_http_transport_rejects_run_when_status_is_running(self):
        transport = HTTPTransport(
            self.cfg,
            route_check=lambda config: None,
        )

        before = {
            "next_seq": 7,
            "state": "RUNNING",
        }

        with patch.object(
            transport,
            "status",
            return_value=before,
        ), patch.object(
            transport,
            "exchange",
        ) as exchange:
            with self.assertRaises(TransportError) as raised:
                transport.command(
                    "a" * 32,
                    "RUN",
                    "L1,W1000,L0",
                )

        self.assertEqual(
            raised.exception.code,
            "DEVICE_BUSY",
        )
        self.assertFalse(raised.exception.uncertain)
        exchange.assert_not_called()


    def test_other_workstation_cannot_query_direct_led_run(self):
        self.app.extensions["workflow"]["locked"] = False

        on = self.post("ON")
        self.assertEqual(on.status_code, 200, on.json)

        other = self.app.test_client()

        response = other.post(
            "/api/experiments/led/status",
            json={"run_id": on.json["run_id"]},
            headers={"Origin": "http://localhost"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["error"], "RUN_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
