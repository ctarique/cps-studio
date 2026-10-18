"""Phase 1 regressions using synthetic credentials and in-memory HTTP fixtures.

The secret-retention, CAR refusal and oversized-header cases reproduce
gateway-probes.py and camera-malformed-length.py from the October 13 audit.
No sockets or live devices are used, and all evidence stores are temporary.
"""
import hashlib
import http.client
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gateway.app import create_app
from gateway.config import Config
from gateway.protocol import sign
from gateway.simulator import Simulator
from gateway.transport import CARHTTPTransport, TransportError

NONCE = "d" * 32


def report(**changes):
    value = {
        "boot": "a" * 32, "next_seq": 1, "run_id": "0" * 32,
        "state": "IDLE", "last_action": "NONE", "motor_a_active": False,
        "motor_b_active": False, "ldr32": 2000, "ldr33": 2000,
        "camera_ready": True, "rssi_dbm": -55, "origin": "DEVICE",
    }
    value.update(changes)
    return value


class SyntheticCAR(CARHTTPTransport):
    """Retain real command preflight/readiness logic; never use the network."""
    def __init__(self, config):
        super().__init__(config, route_check=lambda cfg: None)
        self.current = report()
        self.status_error = None
        self.post_error = None
        self.posts = []

    def status(self):
        if self.status_error:
            raise self.status_error
        return dict(self.current)

    def exchange(self, method, path, body, context):
        self.posts.append((method, path))
        if self.post_error:
            raise self.post_error
        raise AssertionError("This fixture expects refusal or uncertain dispatch")


class GatewayPhase1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(
            data_dir=Path(self.tmp.name), admin_token="a" * 64,
            device_key="b" * 64, car_device_key="c" * 64,
            mode="wifi", device_host="192.168.99.2",
            car_device_host="192.168.99.3",
        )
        self.car = SyntheticCAR(self.cfg)
        self.app = create_app(self.cfg, Simulator(), self.car)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.admin = {"Origin": "http://localhost", "X-Sentinel-Token": self.cfg.admin_token}
        self.workstation = {"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"}
        self.app.extensions["workflow"]["locked"] = False

    def tearDown(self):
        self.app.extensions["ledger"].db.close()
        self.tmp.cleanup()

    def submit(self, source):
        return self.client.post(
            "/api/submissions", json={"source": source, "experiment": "led-status-v1"},
            headers=self.workstation,
        )

    def test_all_known_credentials_are_excluded_from_retained_source(self):
        for key in (self.cfg.admin_token, self.cfg.device_key, self.cfg.car_device_key):
            for source in (key, "// pasted: " + key):
                with self.subTest(credential_length=len(key), embedded=source != key):
                    result = self.submit(source)
                    self.assertEqual(result.status_code, 422)
                    rid = result.json["run_id"]
                    ledger = self.app.extensions["ledger"]
                    self.assertIsNone(ledger.run(rid)["source"])
                    self.assertFalse(ledger.submission(rid)["source_available"])
                    self.assertEqual(
                        ledger.submission(rid)["source_sha256"],
                        hashlib.sha256(source.encode()).hexdigest(),
                    )
                    review = self.client.get(
                        "/api/admin/runs/" + rid + "/review", headers=self.admin,
                    )
                    self.assertIsNone(review.json["source"])
                    self.assertNotIn(key, json.dumps(ledger.export(rid)))

    def test_all_known_credentials_are_rejected_as_observation_hashes(self):
        rid = self.submit("void experiment(){status();}").json["run_id"]
        ledger = self.app.extensions["ledger"]
        for key in (self.cfg.admin_token, self.cfg.device_key, self.cfg.car_device_key):
            result = self.client.post(
                "/api/admin/runs/" + rid + "/observation",
                json={"sha256": key, "kind": "notes"}, headers=self.admin,
            )
            self.assertEqual(result.status_code, 422)
            self.assertEqual(result.json["error"], "OBSERVATION_REFERENCE_INVALID")
        self.assertFalse(any(
            row["class"] == "direct_observation_reference"
            for row in ledger.export(rid)["events"]
        ))

    def test_non_secret_source_and_observation_are_preserved(self):
        source = "void experiment(){status();}"
        rid = self.submit(source).json["run_id"]
        self.assertEqual(self.app.extensions["ledger"].run(rid)["source"], source)
        result = self.client.post(
            "/api/admin/runs/" + rid + "/observation",
            json={"sha256": "e" * 64, "kind": "notes"}, headers=self.admin,
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["physical_validation"], "UNVALIDATED")

    def car_attempt(self, workstation=False):
        if workstation:
            self.app.extensions["lab_display"].idle()
            prepare = self.client.post(
                "/api/display/prepare", json={"experiment": "autonomous-car-v1"},
                headers=self.workstation,
            )
            self.assertEqual(prepare.status_code, 200, prepare.json)
        return self.client.post(
            "/api/experiments/autonomous-car/control" if workstation else "/api/admin/car/control",
            json={"action": "MOTOR_A_TEST"},
            headers=self.workstation if workstation else self.admin,
        )

    def assert_terminal_failure(self, result, stage, disposition, code):
        self.assertEqual(result.json["error"], code)
        rid = result.json["attempt_id"]
        ledger = self.app.extensions["ledger"]
        self.assertEqual(ledger.run(rid)["state"], stage)
        self.assertEqual(self.app.extensions["workflow"]["latest_stage"], stage)
        events = ledger.export(rid)["events"]
        failures = [
            e for e in events if e["class"] == "car_device_communication"
            and e["outcome"] == disposition
        ]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["detail"]["reason"], code)
        self.assertEqual(failures[0]["detail"]["physical_observation"], "NOT_OBSERVED")

    def test_known_readiness_refusals_are_terminal_without_dispatch(self):
        cases = (
            (report(state="RUNNING", motor_a_active=True), "DEVICE_BUSY"),
            (report(state="FAULT"), "DEVICE_NOT_READY"),
            (report(next_seq=99999999), "DEVICE_SEQUENCE_EXHAUSTED"),
        )
        for workstation in (False, True):
            for current, code in cases:
                with self.subTest(workstation=workstation, reason=code):
                    self.car.current = current
                    result = self.car_attempt(workstation)
                    self.assertEqual(result.status_code, 409, result.json)
                    self.assert_terminal_failure(result, "REJECTED", "REJECTED", code)
                    self.assertEqual(self.car.posts, [])
                    self.assertFalse(self.app.extensions["workflow"]["locked"])
                    rid = result.json["attempt_id"]
                    self.assertFalse(any(
                        e["class"] == "device_preflight"
                        for e in self.app.extensions["ledger"].export(rid)["events"]
                    ))

    def test_status_transport_failure_before_dispatch_is_failed(self):
        self.car.status_error = TransportError("TRANSPORT_UNAVAILABLE", False)
        result = self.car_attempt()
        self.assertEqual(result.status_code, 502)
        self.assert_terminal_failure(result, "FAILED", "FAILED", "TRANSPORT_UNAVAILABLE")
        self.assertEqual(self.car.posts, [])
        self.assertFalse(self.app.extensions["workflow"]["locked"])

    def test_uncertain_dispatch_is_incomplete_and_locks(self):
        self.car.post_error = TransportError("TRANSPORT_UNAVAILABLE", True)
        result = self.car_attempt()
        self.assertEqual(result.status_code, 502)
        self.assert_terminal_failure(result, "INCOMPLETE", "UNCERTAIN", "TRANSPORT_UNAVAILABLE")
        self.assertEqual(self.car.posts, [("POST", "/v1/work")])
        self.assertTrue(self.app.extensions["workflow"]["locked"])
        rid = result.json["attempt_id"]
        events = self.app.extensions["ledger"].export(rid)["events"]
        self.assertTrue(any(e["class"] == "device_preflight" for e in events))
        self.assertTrue(any(
            e["class"] == "recovery" and e["outcome"] == "LOCAL_LOCKED" for e in events
        ))

    def test_uncertainty_overrides_a_readiness_reason(self):
        # An injected transport must not make a uncertain outcome appear
        # definitively rejected merely by reusing a readiness error code.
        self.car.post_error = TransportError("DEVICE_BUSY", True)
        result = self.car_attempt()
        self.assert_terminal_failure(result, "INCOMPLETE", "UNCERTAIN", "DEVICE_BUSY")
        self.assertTrue(self.app.extensions["workflow"]["locked"])

    def test_camera_malformed_length_does_not_trigger_global_internal_lock(self):
        self.app.extensions["lab_display"].idle()
        self.client.post(
            "/api/display/prepare", json={"experiment": "autonomous-car-v1"},
            headers=self.workstation,
        )
        wire = camera_wire(self.cfg.car_device_key, length_text="9" * 5000)
        connection = MemoryConnection(wire)
        # Call real CARHTTPTransport.camera via the injected transport; no sockets.
        with patch("gateway.transport.http.client.HTTPConnection", return_value=connection):
            result = self.client.post(
                "/api/experiments/autonomous-car/snapshot",
                json={"mode": "single"}, headers=self.workstation,
            )
        self.assertEqual(result.status_code, 502, result.json)
        self.assertEqual(result.json["error"], "DEVICE_CAMERA_RESPONSE_INVALID")
        workflow = self.app.extensions["workflow"]
        self.assertFalse(workflow["degraded"])
        self.assertFalse(workflow["locked"])
        self.assertEqual(
            self.app.extensions["ledger"].run(result.json["attempt_id"])["state"], "FAILED",
        )
        self.assertNotIn("frames", result.json)


def camera_wire(key, *, length_text=None, frame=b"\xff\xd8sample\xff\xd9",
                digest=None, signature=None, extra_headers=(), omit_length=False,
                content_type="image/jpeg", status=200):
    digest = digest or hashlib.sha256(frame).hexdigest()
    context = "CAMERA\n" + NONCE + "\n" + digest + "\n" + str(len(frame)) + "\n"
    signature = signature or sign(key, context, b"")
    headers = ["Content-Type: " + content_type]
    if not omit_length:
        headers.append("Content-Length: " + (str(len(frame)) if length_text is None else length_text))
    headers.extend(("X-Sentinel-Frame-SHA256: " + digest, "X-Sentinel-Signature: " + signature))
    headers.extend(extra_headers)
    return (
        ("HTTP/1.1 " + str(status) + " Test\r\n" + "\r\n".join(headers) + "\r\n\r\n").encode()
        + frame
    )


class MemorySocket:
    def __init__(self, wire):
        self.wire = wire

    def makefile(self, mode):
        return io.BytesIO(self.wire)

    def shutdown(self, how):
        pass


class MemoryConnection:
    def __init__(self, wire):
        self.sock = MemorySocket(wire)
        self.closed = False
        self.request_args = None

    def connect(self):
        pass

    def request(self, method, path, headers):
        self.request_args = (method, path, headers)

    def getresponse(self):
        response = http.client.HTTPResponse(self.sock)
        response.begin()
        return response

    def close(self):
        self.closed = True


class CameraWirePhase1Tests(unittest.TestCase):
    def setUp(self):
        self.cfg = type("SyntheticConfig", (), {
            "mode": "wifi", "car_device_host": "192.0.2.1", "car_device_key": "c" * 64,
            "car_device_port": 80, "timeout": 2,
        })()
        self.transport = CARHTTPTransport(self.cfg, route_check=lambda cfg: None)

    def invoke(self, wire):
        connection = MemoryConnection(wire)
        with patch("gateway.transport.http.client.HTTPConnection", return_value=connection), \
             patch("gateway.transport.secrets.token_hex", return_value=NONCE):
            try:
                return self.transport.camera()
            finally:
                self.assertTrue(connection.closed)

    def assert_error(self, wire, code):
        with self.assertRaises(TransportError) as caught:
            self.invoke(wire)
        self.assertEqual(caught.exception.code, code)
        self.assertFalse(caught.exception.uncertain)

    def test_5000_digit_content_length_is_normalized(self):
        self.assert_error(
            camera_wire(self.cfg.car_device_key, length_text="9" * 5000),
            "DEVICE_CAMERA_RESPONSE_INVALID",
        )

    def test_bad_length_and_duplicate_headers_are_rejected(self):
        for length in ("", "0", "-1", "01", "65537", "999999", "1.0"):
            with self.subTest(length=length):
                self.assert_error(
                    camera_wire(self.cfg.car_device_key, length_text=length),
                    "DEVICE_CAMERA_RESPONSE_INVALID",
                )
        self.assert_error(
            camera_wire(self.cfg.car_device_key, extra_headers=("Content-Length: 7",)),
            "DEVICE_CAMERA_RESPONSE_INVALID",
        )
        self.assert_error(
            camera_wire(self.cfg.car_device_key, omit_length=True),
            "DEVICE_CAMERA_RESPONSE_INVALID",
        )

    def test_valid_signed_frame_and_maximum_length_are_accepted(self):
        for frame in (b"\xff\xd8sample\xff\xd9", b"\xff\xd8" + b"x" * 65532 + b"\xff\xd9"):
            with self.subTest(length=len(frame)):
                result = self.invoke(camera_wire(self.cfg.car_device_key, frame=frame))
                self.assertEqual(result["jpeg"], frame)
                self.assertEqual(result["length"], len(frame))
                self.assertEqual(result["sha256"], hashlib.sha256(frame).hexdigest())
                self.assertEqual(result["origin"], "DEVICE")

    def test_transfer_encoding_and_wrong_content_type_are_rejected(self):
        self.assert_error(
            camera_wire(self.cfg.car_device_key, extra_headers=("Transfer-Encoding: chunked",)),
            "DEVICE_CAMERA_RESPONSE_INVALID",
        )
        self.assert_error(
            camera_wire(self.cfg.car_device_key, content_type="text/html"),
            "DEVICE_CAMERA_RESPONSE_INVALID",
        )

    def test_truncated_body_digest_and_mac_are_rejected(self):
        self.assert_error(
            camera_wire(self.cfg.car_device_key, length_text="100"),
            "DEVICE_CAMERA_LENGTH_MISMATCH",
        )
        self.assert_error(
            camera_wire(self.cfg.car_device_key, digest="0" * 64),
            "DEVICE_CAMERA_DIGEST_MISMATCH",
        )
        self.assert_error(
            camera_wire(self.cfg.car_device_key, signature="0" * 64),
            "DEVICE_AUTHENTICATION_FAILED",
        )

    def test_http_line_limit_error_is_normalized(self):
        self.assert_error(
            camera_wire(self.cfg.car_device_key, length_text="9" * 70000),
            "TRANSPORT_UNAVAILABLE",
        )

    def test_transport_io_and_http_exceptions_are_normalized(self):
        for error in (TimeoutError("synthetic timeout"), ConnectionResetError("synthetic reset"),
                      http.client.RemoteDisconnected("synthetic close"),
                      http.client.IncompleteRead(b"partial")):
            with self.subTest(error=type(error).__name__):
                connection = MemoryConnection(b"")
                with patch.object(connection, "getresponse", side_effect=error), \
                     patch("gateway.transport.http.client.HTTPConnection", return_value=connection):
                    with self.assertRaises(TransportError) as caught:
                        self.transport.camera()
                self.assertEqual(caught.exception.code, "TRANSPORT_UNAVAILABLE")
                self.assertFalse(caught.exception.uncertain)
                self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
