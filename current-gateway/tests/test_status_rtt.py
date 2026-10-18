"""Host-only CAR RTT regression fixtures: no sockets or physical observations."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gateway.app import create_app
from gateway.config import Config
from gateway.protocol import sign
from gateway.simulator import Simulator
from gateway.status_rtt import StatusRTT
from gateway.transport import CARHTTPTransport, TransportError


class Clock:
    def __init__(self):
        self.ns = 1_000_000_000

    def __call__(self):
        return self.ns


class StatusRTTTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.rtt = StatusRTT(self.clock)

    def success(self, duration_ns=12_345_678):
        started = self.rtt.start()
        self.clock.ns += duration_ns
        self.rtt.succeeded(started)

    def test_initially_unavailable_and_failure_before_success(self):
        self.assertEqual(self.rtt.snapshot(), {
            "state": "UNAVAILABLE", "ms": None, "age_ms": None,
        })
        self.rtt.failed()
        self.assertEqual(self.rtt.snapshot(), {
            "state": "FAILED", "ms": None, "age_ms": None,
        })

    def test_monotonic_application_duration_and_exact_freshness_boundary(self):
        with patch("time.time", side_effect=AssertionError("wall clock forbidden")):
            self.success()
            self.assertEqual(self.rtt.snapshot(), {
                "state": "SUCCESS", "ms": 12.346, "age_ms": 0,
            })
            self.clock.ns += 8_000_000_000
            self.assertEqual(self.rtt.snapshot()["state"], "SUCCESS")
            self.clock.ns += 1
            self.assertEqual(self.rtt.snapshot(), {
                "state": "STALE", "ms": None, "age_ms": 8000,
            })

    def test_failed_attempt_invalidates_value_without_refreshing_success_age(self):
        self.success()
        self.clock.ns += 2_000_000_000
        self.rtt.failed()
        self.assertEqual(self.rtt.snapshot(), {
            "state": "FAILED", "ms": None, "age_ms": 2000,
        })
        self.clock.ns += 9_000_000_000
        self.assertEqual(self.rtt.snapshot()["state"], "FAILED")
        self.assertEqual(self.rtt.snapshot()["age_ms"], 11000)
        self.success(4_000_000)
        self.assertEqual(self.rtt.snapshot(), {
            "state": "SUCCESS", "ms": 4.0, "age_ms": 0,
        })

    def test_unavailable_configuration_never_exposes_fresh_success(self):
        self.success()
        self.assertEqual(self.rtt.snapshot(available=False), {
            "state": "UNAVAILABLE", "ms": None, "age_ms": 0,
        })

    def test_snapshot_cannot_modify_retained_value(self):
        self.success()
        snapshot = self.rtt.snapshot()
        snapshot["ms"] = -1
        self.assertEqual(self.rtt.snapshot()["ms"], 12.346)


class FakeSocket:
    def shutdown(self, how):
        pass


class MemoryResponse:
    status = 200

    def __init__(self, raw, signature):
        self.raw = raw
        self.signature = signature

    def read(self, amount):
        return self.raw[:amount]

    def getheader(self, name):
        return self.signature if name == "X-Sentinel-Signature" else None


class MemoryConnection:
    def __init__(self, response, clock):
        self.response = response
        self.clock = clock
        self.sock = FakeSocket()
        self.requests = []

    def connect(self):
        pass

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path))
        self.clock.ns += 15_000_000

    def getresponse(self):
        return self.response

    def close(self):
        pass


class CARStatusRTTIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Config(
            data_dir=Path(self.tmp.name), admin_token="a" * 64,
            device_key="b" * 64, car_device_key="c" * 64,
            mode="wifi", device_host="192.168.99.2", car_device_host="192.168.99.3",
        )
        self.clock = Clock()
        self.car = CARHTTPTransport(self.cfg, route_check=lambda config: None)
        self.car._status_rtt = StatusRTT(self.clock)
        self.app = create_app(self.cfg, transport=Simulator(), car_transport=self.car)
        self.app.config["TESTING"] = True
        self.addCleanup(self.app.extensions["ledger"].db.close)
        self.client = self.app.test_client()
        self.nonce = "d" * 32
        self.raw = (
            "SCPS1|CAR|" + "e" * 32 + "|1|" + "0" * 32
            + "|IDLE|NONE|0|0|321|654|1|-41|DEVICE"
        ).encode()

    def connection(self, signature=None, raw=None):
        raw = self.raw if raw is None else raw
        if signature is None:
            signature = sign(self.cfg.car_device_key, "STATUS\n" + self.nonce + "\n", raw)
        return MemoryConnection(MemoryResponse(raw, signature), self.clock)

    def status(self, connection):
        with patch("gateway.transport.secrets.token_hex", return_value=self.nonce):
            with patch("gateway.transport.http.client.HTTPConnection", return_value=connection):
                return self.car.status()

    def test_existing_authenticated_get_returns_report_without_timing_fields(self):
        connection = self.connection()
        result = self.status(connection)
        self.assertEqual(connection.requests, [("GET", "/v1/status?nonce=" + self.nonce)])
        self.assertEqual(result["origin"], "DEVICE")
        self.assertEqual(result["rssi_dbm"], -41)
        self.assertNotIn("status_rtt", result)
        self.assertEqual(self.car.status_rtt(), {"state": "SUCCESS", "ms": 15.0, "age_ms": 0})

    def test_bad_signature_or_invalid_signed_payload_never_produces_success(self):
        for connection in (
            self.connection(signature="0" * 64),
            self.connection(raw=b"SCPS1|CAR|invalid"),
        ):
            with self.subTest(raw=connection.response.raw):
                with self.assertRaises(TransportError):
                    self.status(connection)
                self.assertEqual(self.car.status_rtt(), {
                    "state": "FAILED", "ms": None, "age_ms": None,
                })

    def test_unconfigured_device_is_unavailable(self):
        car = CARHTTPTransport(Config(
            data_dir=Path(self.tmp.name), admin_token="a" * 64, device_key="b" * 64,
        ))
        with self.assertRaisesRegex(TransportError, "CAR_NOT_CONFIGURED"):
            car.status()
        self.assertEqual(car.status_rtt(), {"state": "UNAVAILABLE", "ms": None, "age_ms": None})

    def test_telemetry_is_read_only_and_does_not_poll_or_change_evidence(self):
        self.status(self.connection())
        ledger = self.app.extensions["ledger"]
        before_changes = ledger.db.total_changes
        with patch.object(self.car, "status", side_effect=AssertionError("extra poll forbidden")):
            for _ in range(3):
                response = self.client.get("/api/display/devices")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["car"]["status_rtt"], {
                    "state": "SUCCESS", "ms": 15.0, "age_ms": 0,
                })
                for secret in (self.cfg.admin_token, self.cfg.car_device_key, "192.168.99.3", self.nonce):
                    self.assertNotIn(secret, response.get_data(as_text=True))
        self.assertEqual(ledger.db.total_changes, before_changes)
        self.assertIsNone(self.app.extensions["car_telemetry_thread"])

    def test_telemetry_fails_then_recovers_and_expired_success_is_stale(self):
        self.status(self.connection())
        self.clock.ns += 2_000_000_000
        with self.assertRaises(TransportError):
            self.status(self.connection(signature="0" * 64))
        self.assertEqual(self.client.get("/api/display/devices").json["car"]["status_rtt"], {
            "state": "FAILED", "ms": None, "age_ms": 2015,
        })
        self.status(self.connection())
        self.clock.ns += 9_000_000_000
        self.assertEqual(self.client.get("/api/display/devices").json["car"]["status_rtt"], {
            "state": "STALE", "ms": None, "age_ms": 9000,
        })


if __name__ == "__main__":
    unittest.main()
