import tempfile
import unittest

from pathlib import Path

from gateway.app import create_app
from gateway.config import Config
from gateway.simulator import Simulator
from gateway.transport import TransportError


PRIVATE_MARKER = "CAR_PRIVATE_MARKER_MUST_NOT_BE_RETAINED"


def car_report(
    *,
    rid="0" * 32,
    state="IDLE",
    action="NONE",
    motor_a=False,
    motor_b=False,
):
    return {
        "boot":"a" * 32,
        "next_seq":1,
        "run_id":rid,
        "state":state,
        "last_action":action,
        "motor_a_active":motor_a,
        "motor_b_active":motor_b,
        "ldr32":321,
        "ldr33":654,
        "camera_ready":True,
        "rssi_dbm":-41,
        "origin":"DEVICE",

        # Deliberately present in the fake device object.
        # The application evidence path must never retain it.
        "debug_private":PRIVATE_MARKER,
    }


class FakeCar:
    def __init__(
        self,
        *,
        status_error=None,
        command_error=None,
    ):
        self.status_error=status_error
        self.command_error=command_error
        self.status_calls=0
        self.command_calls=[]

    def status(self):
        self.status_calls+=1

        if self.status_error is not None:
            raise self.status_error

        return car_report()

    def command(
        self,
        rid,
        action,
        before_dispatch=None,
    ):
        self.command_calls.append(
            {
                "rid":rid,
                "action":action,
            }
        )

        # DEVICE_BUSY / DEVICE_NOT_READY are pre-dispatch
        # transport decisions. No mutation preflight callback has
        # been retained yet in the current transport contract.
        pre_dispatch_rejections={
            "DEVICE_BUSY",
            "DEVICE_NOT_READY",
            "DEVICE_SEQUENCE_EXHAUSTED",
        }

        if (
            self.command_error is not None
            and self.command_error.code in pre_dispatch_rejections
        ):
            raise self.command_error

        if before_dispatch is not None:
            before_dispatch(
                car_report()
            )

        if self.command_error is not None:
            raise self.command_error

        state=(
            "STOPPED"
            if action=="STOP"
            else "COMPLETE"
        )

        return car_report(
            rid=rid,
            state=state,
            action=action,
        )


class CARApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()

        self.cfg=Config(
            data_dir=Path(self.tmp.name),
            admin_token="1" * 64,
            device_key="2" * 64,
        )

        self.car=FakeCar()

        self.app=create_app(
            self.cfg,
            Simulator(),
            self.car,
        )

        self.client=self.app.test_client()

        self.admin={
            "X-Sentinel-Token":self.cfg.admin_token,
        }

    def tearDown(self):
        self.app.extensions["ledger"].db.close()
        self.tmp.cleanup()

    def test_non_instructor_cannot_call_car_admin_control(self):
        response=self.client.post(
            "/api/admin/car/control",
            json={"action":"STATUS"},
            headers={
                "Origin":"http://localhost",
                "Sec-Fetch-Site":"same-origin",
            },
        )

        self.assertEqual(
            response.status_code,
            401,
            response.json,
        )

        self.assertEqual(
            self.car.status_calls,
            0,
        )

        self.assertEqual(
            self.car.command_calls,
            [],
        )

    def test_status_is_allowed_while_gateway_locked(self):
        self.assertTrue(
            self.app.extensions["workflow"]["locked"]
        )

        response=self.client.post(
            "/api/admin/car/control",
            json={"action":"STATUS"},
            headers=self.admin,
        )

        self.assertEqual(
            response.status_code,
            200,
            response.json,
        )

        self.assertEqual(
            self.car.status_calls,
            1,
        )

        self.assertEqual(
            response.json["reported"]["state"],
            "IDLE",
        )

        self.assertEqual(
            response.json["physical_validation"],
            "UNVALIDATED",
        )

        health=self.client.get("/api/health")

        self.assertEqual(
            health.json["esp32_wrover_health"],
            "CONNECTED",
        )

    def test_motor_test_is_blocked_while_gateway_locked(self):
        response=self.client.post(
            "/api/admin/car/control",
            json={"action":"MOTOR_A_TEST"},
            headers=self.admin,
        )

        self.assertEqual(
            response.status_code,
            409,
            response.json,
        )

        self.assertEqual(
            response.json["error"],
            "GATEWAY_LOCKED",
        )

        self.assertEqual(
            self.car.command_calls,
            [],
        )

    def test_stop_is_allowed_while_gateway_locked(self):
        self.assertTrue(
            self.app.extensions["workflow"]["locked"]
        )

        response=self.client.post(
            "/api/admin/car/control",
            json={"action":"STOP"},
            headers=self.admin,
        )

        self.assertEqual(
            response.status_code,
            200,
            response.json,
        )

        self.assertEqual(
            self.car.command_calls[0]["action"],
            "STOP",
        )

        self.assertEqual(
            response.json["reported"]["state"],
            "STOPPED",
        )

        self.assertTrue(
            self.app.extensions["workflow"]["locked"]
        )

    def test_successful_motor_test_records_only_whitelisted_car_data(self):
        self.app.extensions["workflow"]["locked"]=False

        response=self.client.post(
            "/api/admin/car/control",
            json={"action":"MOTOR_A_TEST"},
            headers=self.admin,
        )

        self.assertEqual(
            response.status_code,
            200,
            response.json,
        )

        rid=response.json["run_id"]

        self.assertEqual(
            response.json["reported"]["last_action"],
            "MOTOR_A_TEST",
        )

        self.assertEqual(
            response.json["physical_validation"],
            "UNVALIDATED",
        )

        rendered_response=str(response.json)

        self.assertNotIn(
            PRIVATE_MARKER,
            rendered_response,
        )

        self.assertNotIn(
            "boot",
            response.json["reported"],
        )

        self.assertNotIn(
            "next_seq",
            response.json["reported"],
        )

        record=self.app.extensions["ledger"].export(rid)
        rendered_record=str(record)

        self.assertNotIn(
            PRIVATE_MARKER,
            rendered_record,
        )

        # Raw CAR protocol freshness data must not be retained.
        self.assertNotIn(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            rendered_record,
        )

    def test_known_busy_rejection_does_not_lock_unlocked_gateway(self):
        self.app.extensions["workflow"]["locked"]=False

        self.car.command_error=TransportError(
            "DEVICE_BUSY",
            False,
        )

        response=self.client.post(
            "/api/admin/car/control",
            json={"action":"MOTOR_B_TEST"},
            headers=self.admin,
        )

        self.assertEqual(
            response.status_code,
            409,
            response.json,
        )

        self.assertEqual(
            response.json["error"],
            "DEVICE_BUSY",
        )

        self.assertFalse(
            self.app.extensions["workflow"]["locked"]
        )

        health=self.client.get("/api/health")

        self.assertEqual(
            health.json["esp32_wrover_health"],
            "CONNECTED",
        )

    def test_uncertain_motor_failure_forces_gateway_locked(self):
        self.app.extensions["workflow"]["locked"]=False

        self.car.command_error=TransportError(
            "TRANSPORT_UNAVAILABLE",
            True,
        )

        response=self.client.post(
            "/api/admin/car/control",
            json={"action":"MOTOR_A_TEST"},
            headers=self.admin,
        )

        self.assertEqual(
            response.status_code,
            502,
            response.json,
        )

        self.assertEqual(
            response.json["error"],
            "TRANSPORT_UNAVAILABLE",
        )

        self.assertTrue(
            self.app.extensions["workflow"]["locked"]
        )

        health=self.client.get("/api/health")

        self.assertEqual(
            health.json["esp32_wrover_health"],
            "UNAVAILABLE",
        )

    def test_missing_car_transport_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            cfg=Config(
                data_dir=Path(td),
                admin_token="4" * 64,
                device_key="5" * 64,
            )

            app=create_app(
                cfg,
                Simulator(),
            )

            try:
                client=app.test_client()

                response=client.post(
                    "/api/admin/car/control",
                    json={"action":"STATUS"},
                    headers={
                        "X-Sentinel-Token":cfg.admin_token,
                    },
                )

                self.assertEqual(
                    response.status_code,
                    422,
                    response.json,
                )

                self.assertEqual(
                    response.json["error"],
                    "EXPERIMENT_UNAVAILABLE",
                )

                health=client.get("/api/health")

                self.assertEqual(
                    health.json["esp32_wrover_health"],
                    "NOT_CONFIGURED",
                )

            finally:
                app.extensions["ledger"].db.close()


if __name__ == "__main__":
    unittest.main()
