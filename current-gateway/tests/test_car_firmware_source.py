import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CAR = ROOT / "esp32" / "sentinel_car"

INO = (
    CAR /
    "sentinel_car.ino"
).read_text()

ENGINE = (
    CAR /
    "car_engine.h"
).read_text()

CONFIG = (
    CAR /
    "sentinel_car_config.example.h"
).read_text()


class CARFirmwareSourceTests(unittest.TestCase):

    def test_public_template_is_unprovisioned(self):
        # A private local provisioning header may exist on an
        # actively configured development Gateway. The public
        # example must remain unprovisioned.
        fields = (
            "SENTINEL_WIFI_SSID",
            "SENTINEL_WIFI_PASSWORD",
            "SENTINEL_GATEWAY_IP",
            "SENTINEL_CAR_DEVICE_KEY",
        )

        for field in fields:
            with self.subTest(field=field):
                declarations = re.findall(
                    r"static\s+const\s+char\s*\*\s*"
                    + re.escape(field)
                    + r'\s*=\s*"([^"]*)"\s*;',
                    CONFIG,
                )

                self.assertEqual(
                    declarations,
                    [""],
                )


    def test_motor_mapping_and_time_bound_are_fixed(self):
        expected = {
            "MOTOR_A_PIN_1": "12",
            "MOTOR_A_PIN_2": "13",
            "MOTOR_B_PIN_1": "14",
            "MOTOR_B_PIN_2": "15",
            "MOTOR_TEST_MS": "120",
        }

        for name, value in expected.items():
            with self.subTest(name=name):
                self.assertRegex(
                    ENGINE,
                    rf"\b{name}\s*=\s*{value}\s*;",
                )

        self.assertIn(
            "pin = MOTOR_A_PIN_1;",
            ENGINE,
        )

        self.assertIn(
            "pin = MOTOR_B_PIN_1;",
            ENGINE,
        )

        self.assertNotIn(
            "activePin = MOTOR_A_PIN_2",
            ENGINE,
        )

        self.assertNotIn(
            "activePin = MOTOR_B_PIN_2",
            ENGINE,
        )


    def test_command_parser_accepts_only_bounded_semantics(self):
        actions = re.findall(
            r'!strcmp\(\s*action,\s*"([A-Z_]+)"\s*\)',
            INO,
        )

        self.assertEqual(
            set(actions),
            {
                "MOTOR_A_TEST",
                "MOTOR_A_CW_TEST",
                "MOTOR_A_CCW_TEST",
                "MOTOR_B_TEST",
                "MOTOR_B_CW_TEST",
                "MOTOR_B_CCW_TEST",
                "STOP",
            },
        )

        for forbidden in (
            "FORWARD",
            "REVERSE",
            "LEFT",
            "RIGHT",
        ):
            self.assertNotIn(
                f'"{forbidden}"',
                INO,
            )

        self.assertIn(
            "char* fields[6]",
            INO,
        )

        self.assertIn(
            "count != 6",
            INO,
        )

        self.assertIn(
            "fields[5]",
            INO,
        )


    def test_authenticated_report_wire_shape_matches_gateway_contract(self):
        self.assertIn(
            '"SCPS1|CAR|%s|%lu|%s|%s|%s|%d|%d|%u|%u|%d|%d|DEVICE"',
            INO,
        )

        self.assertIn(
            'strcmp(fields[1], "CAR")',
            INO,
        )


    def test_hmac_contexts_and_gateway_peer_gate_are_present(self):
        self.assertIn(
            '"POST\\n/v1/work\\n"',
            INO,
        )

        self.assertIn(
            'String("STATUS\\n")',
            INO,
        )

        self.assertIn(
            'String("RESULT\\n")',
            INO,
        )

        self.assertRegex(
            INO,
            r"peer\.remoteIP\(\)\s*!=\s*gatewayIP",
        )


    def test_boot_sequence_run_and_replay_checks_are_bounded(self):
        self.assertIn(
            "strcmp(fields[2], bootID)",
            INO,
        )

        self.assertIn(
            "lowercaseHex(fields[4], 32)",
            INO,
        )

        self.assertIn(
            "99999998",
            INO,
        )

        self.assertIn(
            "requestedSequence != sequence",
            INO,
        )

        self.assertIn(
            "++sequence;",
            INO,
        )


    def test_wifi_loss_forces_motor_stop(self):
        self.assertRegex(
            INO,
            r"(?s)WiFi\.status\(\)\s*!=\s*"
            r"WL_CONNECTED\s*\)\s*\{"
            r".*?engine\.stop\(false\);"
            r".*?server\.end\(\);",
        )


    def test_sensor_and_camera_mapping_are_fixed(self):
        self.assertRegex(
            INO,
            r"LDR_32_PIN\s*=\s*32\s*;",
        )

        self.assertRegex(
            INO,
            r"LDR_33_PIN\s*=\s*33\s*;",
        )

        expected_camera = {
            "CAMERA_XCLK": 21,
            "CAMERA_SIOD": 26,
            "CAMERA_SIOC": 27,
            "CAMERA_Y9": 35,
            "CAMERA_Y8": 34,
            "CAMERA_Y7": 39,
            "CAMERA_Y6": 36,
            "CAMERA_Y5": 19,
            "CAMERA_Y4": 18,
            "CAMERA_Y3": 5,
            "CAMERA_Y2": 4,
            "CAMERA_VSYNC": 25,
            "CAMERA_HREF": 23,
            "CAMERA_PCLK": 22,
        }

        for name, pin in expected_camera.items():
            with self.subTest(name=name):
                self.assertRegex(
                    INO,
                    rf"\b{name}\s*=\s*{pin}\s*;",
                )


if __name__ == "__main__":
    unittest.main()
