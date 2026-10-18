import unittest

from gateway.protocol import (
    MAX_COMMAND_SEQUENCE,
    car_work,
    parse_car_status,
)


BOOT = "a" * 32
RID = "b" * 32


def report(
    *,
    seq=1,
    rid=RID,
    state="IDLE",
    action="NONE",
    motor_a="0",
    motor_b="0",
    ldr32="0",
    ldr33="0",
    camera="1",
    rssi="-24",
    origin="DEVICE",
    profile="CAR",
):
    return (
        f"SCPS1|{profile}|{BOOT}|{seq}|{rid}|{state}|{action}|"
        f"{motor_a}|{motor_b}|{ldr32}|{ldr33}|{camera}|{rssi}|{origin}"
    ).encode()


class CarProtocolTests(unittest.TestCase):
    def test_semantic_motor_command(self):
        self.assertEqual(
            car_work(BOOT, 1, RID, "MOTOR_A_TEST"),
            f"SCPS1|CAR|{BOOT}|1|{RID}|MOTOR_A_TEST".encode(),
        )

    def test_stop_command(self):
        self.assertEqual(
            car_work(BOOT, 7, RID, "STOP"),
            f"SCPS1|CAR|{BOOT}|7|{RID}|STOP".encode(),
        )

    def test_arbitrary_gpio_and_duration_are_rejected(self):
        for action in ("GPIO12", "GPIO14_HIGH", "MOTOR_A_5000MS", "FORWARD"):
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    car_work(BOOT, 1, RID, action)

    def test_sequence_bounds(self):
        with self.assertRaises(ValueError):
            car_work(BOOT, 0, RID, "STOP")

        self.assertEqual(
            car_work(BOOT, MAX_COMMAND_SEQUENCE, RID, "STOP"),
            f"SCPS1|CAR|{BOOT}|{MAX_COMMAND_SEQUENCE}|{RID}|STOP".encode(),
        )

        with self.assertRaises(ValueError):
            car_work(BOOT, MAX_COMMAND_SEQUENCE + 1, RID, "STOP")

    def test_valid_authenticated_payload_shape(self):
        value = parse_car_status(
            report(
                seq=2,
                state="COMPLETE",
                action="MOTOR_A_TEST",
                ldr32="3673",
                ldr33="3724",
                camera="1",
                rssi="-24",
            )
        )

        self.assertEqual(value["boot"], BOOT)
        self.assertEqual(value["next_seq"], 2)
        self.assertEqual(value["run_id"], RID)
        self.assertEqual(value["state"], "COMPLETE")
        self.assertEqual(value["last_action"], "MOTOR_A_TEST")
        self.assertFalse(value["motor_a_active"])
        self.assertFalse(value["motor_b_active"])
        self.assertEqual(value["ldr32"], 3673)
        self.assertEqual(value["ldr33"], 3724)
        self.assertTrue(value["camera_ready"])
        self.assertEqual(value["rssi_dbm"], -24)
        self.assertEqual(value["origin"], "DEVICE")

    def test_running_motor_report_is_allowed(self):
        value = parse_car_status(
            report(
                state="RUNNING",
                action="MOTOR_B_TEST",
                motor_b="1",
            )
        )
        self.assertTrue(value["motor_b_active"])

    def test_terminal_state_cannot_claim_energized_motor(self):
        for state in ("IDLE", "COMPLETE", "STOPPED", "FAULT"):
            with self.subTest(state=state):
                with self.assertRaises(ValueError):
                    parse_car_status(
                        report(
                            state=state,
                            action="MOTOR_A_TEST",
                            motor_a="1",
                        )
                    )

    def test_sensor_and_rssi_bounds(self):
        for kwargs in (
            {"ldr32": "4096"},
            {"ldr33": "4096"},
            {"rssi": "-128"},
            {"rssi": "1"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    parse_car_status(report(**kwargs))

    def test_wrong_profile_and_unknown_action_rejected(self):
        with self.assertRaises(ValueError):
            parse_car_status(report(profile="CAM"))

        with self.assertRaises(ValueError):
            parse_car_status(report(action="GPIO12"))


if __name__ == "__main__":
    unittest.main()
