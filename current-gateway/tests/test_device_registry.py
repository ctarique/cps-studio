import tempfile
import unittest

from pathlib import Path

from gateway.app import create_app
from gateway.config import Config
from gateway.simulator import Simulator
from gateway.transport import CARHTTPTransport, HTTPTransport


class FakeCarTransport:
    pass


class DeviceRegistryTests(unittest.TestCase):
    def config(self, data_dir, **extra):
        return Config(
            data_dir=Path(data_dir),
            admin_token="1" * 64,
            device_key="2" * 64,
            **extra,
        )

    def test_existing_transport_argument_remains_cam(self):
        with tempfile.TemporaryDirectory() as td:
            cam = Simulator()

            app = create_app(
                self.config(td),
                cam,
            )

            self.assertIs(
                app.extensions["transport"],
                cam,
            )

            self.assertEqual(
                app.extensions["devices"],
                {
                    "esp32-cam": cam,
                },
            )

            app.extensions["ledger"].db.close()

    def test_explicit_car_transport_has_separate_registry_identity(self):
        with tempfile.TemporaryDirectory() as td:
            cam = Simulator()
            car = FakeCarTransport()

            app = create_app(
                self.config(td),
                cam,
                car,
            )

            devices = app.extensions["devices"]

            self.assertIs(
                devices["esp32-cam"],
                cam,
            )

            self.assertIs(
                devices["esp32-wrover"],
                car,
            )

            self.assertIsNot(
                devices["esp32-cam"],
                devices["esp32-wrover"],
            )

            self.assertIs(
                app.extensions["transport"],
                cam,
            )

            app.extensions["ledger"].db.close()

    def test_wifi_configuration_registers_separate_real_transports(self):
        with tempfile.TemporaryDirectory() as td:
            app = create_app(
                Config(
                    data_dir=Path(td),
                    admin_token="1" * 64,
                    device_key="2" * 64,
                    car_device_key="3" * 64,
                    mode="wifi",
                    device_host="192.168.99.2",
                    device_port=80,
                    car_device_host="192.168.99.3",
                    car_device_port=80,
                    wifi_interface="wlan0",
                )
            )

            devices = app.extensions["devices"]

            self.assertEqual(
                set(devices),
                {
                    "esp32-cam",
                    "esp32-wrover",
                },
            )

            self.assertIsInstance(
                devices["esp32-cam"],
                HTTPTransport,
            )

            self.assertIsInstance(
                devices["esp32-wrover"],
                CARHTTPTransport,
            )

            self.assertIs(
                app.extensions["transport"],
                devices["esp32-cam"],
            )

            self.assertIsNot(
                devices["esp32-cam"],
                devices["esp32-wrover"],
            )

            app.extensions["ledger"].db.close()


if __name__ == "__main__":
    unittest.main()
