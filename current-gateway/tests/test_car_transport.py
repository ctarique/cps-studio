import hashlib
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from gateway.config import Config
from gateway.protocol import car_work, sign
from gateway.transport import CARHTTPTransport, TransportError


BOOT = "a" * 32
RID = "b" * 32


def status_value(
    *,
    boot=BOOT,
    next_seq=1,
    rid="0" * 32,
    state="IDLE",
    action="NONE",
    motor_a=False,
    motor_b=False,
    ldr32=100,
    ldr33=200,
    camera=True,
    rssi=-40,
):
    return {
        "boot": boot,
        "next_seq": next_seq,
        "run_id": rid,
        "state": state,
        "last_action": action,
        "motor_a_active": motor_a,
        "motor_b_active": motor_b,
        "ldr32": ldr32,
        "ldr33": ldr33,
        "camera_ready": camera,
        "rssi_dbm": rssi,
        "origin": "DEVICE",
    }


def raw_report(
    *,
    boot=BOOT,
    seq=1,
    rid="0" * 32,
    state="IDLE",
    action="NONE",
    motor_a="0",
    motor_b="0",
    ldr32="100",
    ldr33="200",
    camera="1",
    rssi="-40",
):
    return (
        f"SCPS1|CAR|{boot}|{seq}|{rid}|{state}|{action}|"
        f"{motor_a}|{motor_b}|{ldr32}|{ldr33}|{camera}|{rssi}|DEVICE"
    ).encode()


class FakeSocket:
    def shutdown(self, how):
        pass


class FakeResponse:
    def __init__(self, raw, signature, status=200):
        self.raw = raw
        self.signature = signature
        self.status = status

    def read(self, amount):
        return self.raw[:amount]

    def getheader(self, name):
        if name == "X-Sentinel-Signature":
            return self.signature
        return None


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.sock = FakeSocket()
        self.request_args = None
        self.closed = False

    def connect(self):
        pass

    def request(self, method, path, body=None, headers=None):
        self.request_args = {
            "method": method,
            "path": path,
            "body": body,
            "headers": headers or {},
        }

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class StubCARTransport(CARHTTPTransport):
    def __init__(self, config, before, result):
        super().__init__(config, route_check=lambda config: None)
        self.before = before
        self.result = result
        self.dispatched = []

    def status(self):
        return dict(self.before)

    def exchange(self, method, path, body, context):
        self.dispatched.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "context": context,
            }
        )
        return dict(self.result)


class CARTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

        self.cfg = Config(
            data_dir=Path(self.tmp.name),
            admin_token="1" * 64,
            device_key="2" * 64,
            car_device_key="3" * 64,
            mode="wifi",
            device_host="192.168.99.2",
            device_port=80,
            car_device_host="192.168.99.3",
            car_device_port=80,
            wifi_interface="wlan0",
            timeout=2,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_unconfigured_car_fails_closed(self):
        cfg = Config(
            data_dir=Path(self.tmp.name),
            admin_token="1" * 64,
            device_key="2" * 64,
        )

        transport = CARHTTPTransport(cfg)

        with self.assertRaisesRegex(
            TransportError,
            "CAR_NOT_CONFIGURED",
        ):
            transport.status()

    def test_get_uses_car_endpoint_and_car_key(self):
        nonce = "c" * 32
        context = "STATUS\n" + nonce + "\n"
        raw = raw_report()
        signature = sign(
            self.cfg.car_device_key,
            context,
            raw,
        )

        fake = FakeConnection(
            FakeResponse(raw, signature)
        )

        transport = CARHTTPTransport(
            self.cfg,
            route_check=lambda config: None,
        )

        with patch(
            "gateway.transport.http.client.HTTPConnection",
            return_value=fake,
        ) as connection:
            result = transport.exchange(
                "GET",
                "/v1/status?nonce=" + nonce,
                b"",
                context,
            )

        connection.assert_called_once_with(
            "192.168.99.3",
            80,
            timeout=2,
        )

        self.assertEqual(result["origin"], "DEVICE")
        self.assertEqual(result["ldr32"], 100)
        self.assertEqual(
            fake.request_args["path"],
            "/v1/status?nonce=" + nonce,
        )
        self.assertNotIn(
            "X-Sentinel-Signature",
            fake.request_args["headers"],
        )

    def test_cam_key_cannot_authenticate_car_response(self):
        nonce = "c" * 32
        context = "STATUS\n" + nonce + "\n"
        raw = raw_report()

        wrong_signature = sign(
            self.cfg.device_key,
            context,
            raw,
        )

        fake = FakeConnection(
            FakeResponse(raw, wrong_signature)
        )

        transport = CARHTTPTransport(
            self.cfg,
            route_check=lambda config: None,
        )

        with patch(
            "gateway.transport.http.client.HTTPConnection",
            return_value=fake,
        ):
            with self.assertRaisesRegex(
                TransportError,
                "DEVICE_AUTHENTICATION_FAILED",
            ):
                transport.exchange(
                    "GET",
                    "/v1/status?nonce=" + nonce,
                    b"",
                    context,
                )

    def test_post_is_signed_with_car_key(self):
        body = car_work(
            BOOT,
            1,
            RID,
            "MOTOR_A_TEST",
        )

        context = (
            "RESULT\n"
            + hashlib.sha256(body).hexdigest()
            + "\n"
        )

        raw = raw_report(
            seq=2,
            rid=RID,
            state="COMPLETE",
            action="MOTOR_A_TEST",
        )

        signature = sign(
            self.cfg.car_device_key,
            context,
            raw,
        )

        fake = FakeConnection(
            FakeResponse(raw, signature)
        )

        transport = CARHTTPTransport(
            self.cfg,
            route_check=lambda config: None,
        )

        with patch(
            "gateway.transport.http.client.HTTPConnection",
            return_value=fake,
        ):
            transport.exchange(
                "POST",
                "/v1/work",
                body,
                context,
            )

        self.assertEqual(
            fake.request_args["headers"][
                "X-Sentinel-Signature"
            ],
            sign(
                self.cfg.car_device_key,
                "POST\n/v1/work\n",
                body,
            ),
        )

        self.assertNotEqual(
            fake.request_args["headers"][
                "X-Sentinel-Signature"
            ],
            sign(
                self.cfg.device_key,
                "POST\n/v1/work\n",
                body,
            ),
        )

    def test_motor_a_command_uses_authenticated_preflight(self):
        before = status_value()

        result = status_value(
            next_seq=2,
            rid=RID,
            state="COMPLETE",
            action="MOTOR_A_TEST",
        )

        transport = StubCARTransport(
            self.cfg,
            before,
            result,
        )

        retained = {}

        def retain(report):
            retained.update(report)

            # Prove caller mutation cannot alter the command freshness
            # values retained inside the transport.
            report["next_seq"] = 999

        returned = transport.command(
            RID,
            "MOTOR_A_TEST",
            before_dispatch=retain,
        )

        self.assertEqual(
            retained["next_seq"],
            1,
        )

        self.assertEqual(
            transport.dispatched[0]["body"],
            car_work(
                BOOT,
                1,
                RID,
                "MOTOR_A_TEST",
            ),
        )

        self.assertEqual(
            returned["state"],
            "COMPLETE",
        )

    def test_running_device_blocks_new_motor_test(self):
        before = status_value(
            state="RUNNING",
            action="MOTOR_A_TEST",
            motor_a=True,
        )

        result = status_value(
            next_seq=2,
            rid=RID,
            state="COMPLETE",
            action="MOTOR_B_TEST",
        )

        transport = StubCARTransport(
            self.cfg,
            before,
            result,
        )

        with self.assertRaisesRegex(
            TransportError,
            "DEVICE_BUSY",
        ):
            transport.command(
                RID,
                "MOTOR_B_TEST",
            )

        self.assertEqual(
            transport.dispatched,
            [],
        )

    def test_fault_blocks_motor_test_but_allows_stop(self):
        before = status_value(
            state="FAULT",
        )

        result = status_value(
            next_seq=2,
            rid=RID,
            state="STOPPED",
            action="STOP",
        )

        transport = StubCARTransport(
            self.cfg,
            before,
            result,
        )

        with self.assertRaisesRegex(
            TransportError,
            "DEVICE_NOT_READY",
        ):
            transport.command(
                RID,
                "MOTOR_A_TEST",
            )

        self.assertEqual(
            transport.dispatched,
            [],
        )

        stopped = transport.command(
            RID,
            "STOP",
        )

        self.assertEqual(
            stopped["state"],
            "STOPPED",
        )

    def test_sequence_exhaustion_prevents_dispatch(self):
        before = status_value(
            next_seq=99999999,
        )

        result = status_value(
            next_seq=99999999,
            rid=RID,
            state="STOPPED",
            action="STOP",
        )

        transport = StubCARTransport(
            self.cfg,
            before,
            result,
        )

        with self.assertRaisesRegex(
            TransportError,
            "DEVICE_SEQUENCE_EXHAUSTED",
        ):
            transport.command(
                RID,
                "STOP",
            )

        self.assertEqual(
            transport.dispatched,
            [],
        )

    def test_response_identity_mismatch_is_uncertain(self):
        cases = (
            {"boot": "c" * 32},
            {"next_seq": 7},
            {"run_id": "d" * 32},
        )

        for change in cases:
            with self.subTest(change=change):
                result = status_value(
                    next_seq=2,
                    rid=RID,
                    state="COMPLETE",
                    action="MOTOR_A_TEST",
                )

                result.update(change)

                transport = StubCARTransport(
                    self.cfg,
                    status_value(),
                    result,
                )

                with self.assertRaisesRegex(
                    TransportError,
                    "DEVICE_RESPONSE_MISMATCH",
                ) as caught:
                    transport.command(
                        RID,
                        "MOTOR_A_TEST",
                    )

                self.assertTrue(
                    caught.exception.uncertain
                )

    def test_response_action_mismatch_is_uncertain(self):
        result = status_value(
            next_seq=2,
            rid=RID,
            state="COMPLETE",
            action="MOTOR_B_TEST",
        )

        transport = StubCARTransport(
            self.cfg,
            status_value(),
            result,
        )

        with self.assertRaisesRegex(
            TransportError,
            "DEVICE_ACTION_MISMATCH",
        ) as caught:
            transport.command(
                RID,
                "MOTOR_A_TEST",
            )

        self.assertTrue(
            caught.exception.uncertain
        )

    def test_semantic_result_consistency(self):
        cases = (
            (
                "MOTOR_A_TEST",
                status_value(
                    next_seq=2,
                    rid=RID,
                    state="RUNNING",
                    action="MOTOR_A_TEST",
                    motor_a=False,
                    motor_b=True,
                ),
                "DEVICE_CAR_RESULT_INCONSISTENT",
            ),
            (
                "MOTOR_B_TEST",
                status_value(
                    next_seq=2,
                    rid=RID,
                    state="RUNNING",
                    action="MOTOR_B_TEST",
                    motor_a=True,
                    motor_b=False,
                ),
                "DEVICE_CAR_RESULT_INCONSISTENT",
            ),
            (
                "STOP",
                status_value(
                    next_seq=2,
                    rid=RID,
                    state="COMPLETE",
                    action="STOP",
                ),
                "DEVICE_STOP_INCONSISTENT",
            ),
        )

        for action, result, code in cases:
            with self.subTest(action=action):
                transport = StubCARTransport(
                    self.cfg,
                    status_value(),
                    result,
                )

                with self.assertRaisesRegex(
                    TransportError,
                    code,
                ) as caught:
                    transport.command(
                        RID,
                        action,
                    )

                self.assertTrue(
                    caught.exception.uncertain
                )


if __name__ == "__main__":
    unittest.main()
