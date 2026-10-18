import hashlib
import tempfile
import unittest
from pathlib import Path

from gateway.app import create_app
from gateway.config import Config
from gateway.simulator import Simulator
from gateway.transport import TransportError


def car_report(
    *,
    rid="0" * 32,
    state="IDLE",
    action="NONE",
    motor_a=False,
    motor_b=False,
):
    return {
        "boot": "a" * 32,
        "next_seq": 1,
        "run_id": rid,
        "state": state,
        "last_action": action,
        "motor_a_active": motor_a,
        "motor_b_active": motor_b,
        "ldr32": 321,
        "ldr33": 654,
        "camera_ready": True,
        "rssi_dbm": -41,
        "origin": "DEVICE",
    }


class FakeExperimentCar:

    def __init__(self):
        self.status_calls = 0
        self.command_calls = []
        self.camera_calls = 0
        self.camera_error = None
        self.camera_frames = []

    def status(self):
        self.status_calls += 1
        return car_report()

    def command(
        self,
        rid,
        action,
        before_dispatch=None,
    ):
        self.command_calls.append(
            {
                "rid": rid,
                "action": action,
            }
        )

        if before_dispatch is not None:
            before_dispatch(
                car_report()
            )

        state = (
            "STOPPED"
            if action == "STOP"
            else "COMPLETE"
        )

        return car_report(
            rid=rid,
            state=state,
            action=action,
        )

    def camera(self):
        self.camera_calls += 1

        if self.camera_error is not None:
            raise self.camera_error

        frame = (
            b"\xff\xd8"
            + (
                "SENTINEL-CAR-FRAME-%d"
                % self.camera_calls
            ).encode("ascii")
            + b"\xff\xd9"
        )

        digest = hashlib.sha256(
            frame
        ).hexdigest()

        self.camera_frames.append(
            frame
        )

        return {
            "jpeg": frame,
            "sha256": digest,
            "length": len(frame),
            "origin": "DEVICE",
        }


class CARExperimentTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

        self.cfg = Config(
            data_dir=Path(self.tmp.name),
            admin_token="1" * 64,
            device_key="2" * 64,
            mode="simulator",
            device_host="127.0.0.1",
        )

        self.car = FakeExperimentCar()

        self.app = create_app(
            self.cfg,
            Simulator(),
            self.car,
        )

        self.app.config["TESTING"] = True

        self.client = self.app.test_client()

        self.workstation = {
            "Origin": "http://localhost",
            "Sec-Fetch-Site": "same-origin",
        }

        self.admin = {
            "Origin": "http://localhost",
            "X-Sentinel-Token":
                self.cfg.admin_token,
        }

    def tearDown(self):
        self.app.extensions["ledger"].db.close()
        self.tmp.cleanup()

    def unlock(self):
        response = self.client.post(
            "/api/admin/recovery",
            json={"action": "UNLOCK"},
            headers=self.admin,
        )

        self.assertEqual(
            response.status_code,
            200,
            response.json,
        )

        self.assertFalse(
            response.json["locked"]
        )

    def prepare_car(self):
        self.unlock()

        response = self.client.post(
            "/api/display/prepare",
            json={
                "experiment":
                    "autonomous-car-v1"
            },
            headers=self.workstation,
        )

        self.assertEqual(
            response.status_code,
            200,
            response.json,
        )

        self.assertEqual(
            response.json["experiment"],
            "autonomous-car",
        )

        self.assertEqual(
            response.json["mode"],
            "AUTONOMOUS_CAR_SETUP",
        )

    def car_control(self, action):
        return self.client.post(
            "/api/experiments/"
            "autonomous-car/control",
            json={"action": action},
            headers=self.workstation,
        )

    def snapshot(self, mode):
        return self.client.post(
            "/api/experiments/"
            "autonomous-car/snapshot",
            json={"mode": mode},
            headers=self.workstation,
        )

    def test_origin_is_required(self):
        response = self.client.post(
            "/api/experiments/"
            "autonomous-car/control",
            json={
                "action":
                    "MOTOR_A_TEST"
            },
        )

        self.assertEqual(
            response.status_code,
            403,
            response.json,
        )

        self.assertEqual(
            response.json["error"],
            "ORIGIN_REQUIRED",
        )

        self.assertEqual(
            self.car.command_calls,
            [],
        )

    def test_car_context_is_required(self):
        self.unlock()

        response = self.car_control(
            "MOTOR_A_TEST"
        )

        self.assertEqual(
            response.status_code,
            409,
            response.json,
        )

        self.assertEqual(
            response.json["error"],
            "CAR_EXPERIMENT_NOT_READY",
        )

        self.assertEqual(
            self.car.command_calls,
            [],
        )

    def test_bounded_motor_a_and_b_actions(self):
        self.prepare_car()

        for action in (
            "MOTOR_A_TEST",
            "MOTOR_B_TEST",
        ):
            with self.subTest(action=action):
                response = self.car_control(
                    action
                )

                self.assertEqual(
                    response.status_code,
                    200,
                    response.json,
                )

                self.assertEqual(
                    response.json["action"],
                    action,
                )

                self.assertEqual(
                    response.json[
                        "reported"
                    ]["last_action"],
                    action,
                )

                self.assertEqual(
                    response.json[
                        "physical_validation"
                    ],
                    "UNVALIDATED",
                )

        self.assertEqual(
            [
                call["action"]
                for call
                in self.car.command_calls
            ],
            [
                "MOTOR_A_TEST",
                "MOTOR_B_TEST",
            ],
        )

    def test_arbitrary_motor_action_is_rejected(self):
        self.prepare_car()

        response = self.car_control(
            "GPIO12_HIGH"
        )

        self.assertEqual(
            response.status_code,
            422,
            response.json,
        )

        self.assertEqual(
            response.json["error"],
            "CAR_ACTION_NOT_ALLOWED",
        )

        self.assertEqual(
            self.car.command_calls,
            [],
        )

    def test_invalid_snapshot_mode_is_rejected(self):
        self.prepare_car()

        response = self.snapshot(
            "continuous"
        )

        self.assertEqual(
            response.status_code,
            422,
            response.json,
        )

        self.assertEqual(
            response.json["error"],
            "CAR_CAMERA_MODE_NOT_ALLOWED",
        )

        self.assertEqual(
            self.car.camera_calls,
            0,
        )

    def test_single_snapshot_is_retrievable(self):
        self.prepare_car()

        response = self.snapshot(
            "single"
        )

        self.assertEqual(
            response.status_code,
            200,
            response.json,
        )

        self.assertEqual(
            response.json["frame_count"],
            1,
        )

        self.assertEqual(
            response.json["mode"],
            "single",
        )

        self.assertEqual(
            response.json["origin"],
            "DEVICE",
        )

        self.assertEqual(
            response.json[
                "physical_validation"
            ],
            "UNVALIDATED",
        )

        frame = response.json["frames"][0]

        self.assertEqual(
            frame["origin"],
            "DEVICE",
        )

        image = self.client.get(
            frame["url"]
        )

        self.assertEqual(
            image.status_code,
            200,
        )

        self.assertEqual(
            image.mimetype,
            "image/jpeg",
        )

        self.assertEqual(
            image.data,
            self.car.camera_frames[0],
        )

        self.assertEqual(
            image.headers[
                "X-Sentinel-Frame-SHA256"
            ],
            frame["sha256"],
        )

        devices = self.client.get(
            "/api/display/devices"
        )

        self.assertEqual(
            devices.status_code,
            200,
        )

        self.assertTrue(
            devices.json["car"][
                "camera_active"
            ]
        )

    def test_snapshot_is_scoped_to_workstation(self):
        self.prepare_car()

        response = self.snapshot(
            "single"
        )

        self.assertEqual(
            response.status_code,
            200,
            response.json,
        )

        url = response.json[
            "frames"
        ][0]["url"]

        other = self.app.test_client()

        denied = other.get(
            url
        )

        self.assertEqual(
            denied.status_code,
            404,
            denied.json,
        )

        self.assertEqual(
            denied.json["error"],
            "SNAPSHOT_NOT_FOUND",
        )

    def test_series_is_exactly_three_frames(self):
        self.prepare_car()

        response = self.snapshot(
            "series"
        )

        self.assertEqual(
            response.status_code,
            200,
            response.json,
        )

        self.assertEqual(
            response.json["mode"],
            "series",
        )

        self.assertEqual(
            response.json["frame_count"],
            3,
        )

        self.assertEqual(
            len(response.json["frames"]),
            3,
        )

        self.assertEqual(
            self.car.camera_calls,
            3,
        )

        urls = {
            frame["url"]
            for frame
            in response.json["frames"]
        }

        self.assertEqual(
            len(urls),
            3,
        )

        for frame in response.json["frames"]:
            image = self.client.get(
                frame["url"]
            )

            self.assertEqual(
                image.status_code,
                200,
            )

            self.assertEqual(
                image.mimetype,
                "image/jpeg",
            )

    def test_gallery_is_empty_before_capture(self):
        response = self.client.get(
            "/experiments/autonomous-car/gallery"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        html = response.get_data(
            as_text=True
        )

        self.assertIn(
            "No recent captures from this workstation session.",
            html,
        )

    def test_gallery_lists_current_workstation_capture(self):
        self.prepare_car()

        capture = self.snapshot(
            "single"
        )

        self.assertEqual(
            capture.status_code,
            200,
            capture.json,
        )

        frame = capture.json[
            "frames"
        ][0]

        gallery = self.client.get(
            "/experiments/autonomous-car/gallery"
        )

        self.assertEqual(
            gallery.status_code,
            200,
        )

        html = gallery.get_data(
            as_text=True
        )

        self.assertIn(
            frame["url"],
            html,
        )

        self.assertIn(
            frame["sha256"][:12],
            html,
        )

    def test_gallery_hides_other_workstation_capture(self):
        self.prepare_car()

        capture = self.snapshot(
            "single"
        )

        self.assertEqual(
            capture.status_code,
            200,
            capture.json,
        )

        frame = capture.json[
            "frames"
        ][0]

        other = self.app.test_client()

        gallery = other.get(
            "/experiments/autonomous-car/gallery"
        )

        self.assertEqual(
            gallery.status_code,
            200,
        )

        html = gallery.get_data(
            as_text=True
        )

        self.assertNotIn(
            frame["url"],
            html,
        )

        self.assertIn(
            "No recent captures from this workstation session.",
            html,
        )

    def test_gallery_is_bounded_to_twelve_recent_captures(self):
        self.prepare_car()

        urls = []

        for _ in range(13):
            capture = self.snapshot(
                "single"
            )

            self.assertEqual(
                capture.status_code,
                200,
                capture.json,
            )

            urls.append(
                capture.json[
                    "frames"
                ][0]["url"]
            )

        gallery = self.client.get(
            "/experiments/autonomous-car/gallery"
        )

        self.assertEqual(
            gallery.status_code,
            200,
        )

        html = gallery.get_data(
            as_text=True
        )

        visible = [
            url
            for url in urls
            if url in html
        ]

        self.assertEqual(
            len(visible),
            12,
        )

        self.assertNotIn(
            urls[0],
            html,
        )

        self.assertIn(
            urls[-1],
            html,
        )

    def test_failed_capture_does_not_claim_activity(self):
        self.prepare_car()

        self.car.camera_error = (
            TransportError(
                "CAR_CAMERA_UNAVAILABLE"
            )
        )

        response = self.snapshot(
            "single"
        )

        self.assertEqual(
            response.status_code,
            503,
            response.json,
        )

        self.assertEqual(
            response.json["error"],
            "CAR_CAMERA_UNAVAILABLE",
        )

        devices = self.client.get(
            "/api/display/devices"
        )

        self.assertEqual(
            devices.status_code,
            200,
        )

        self.assertFalse(
            devices.json["car"][
                "camera_active"
            ]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
