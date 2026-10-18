import tempfile
import unittest
from pathlib import Path

from gateway.app import create_app
from gateway.config import Config
from gateway.simulator import Simulator


class WorkstationSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(
            data_dir=Path(self.tmp.name),
            admin_token="2" * 64,
            device_key="3" * 64,
        )
        self.app = create_app(self.cfg, Simulator())
        self.client = self.app.test_client()
        self.origin = {"Origin": "http://localhost"}

    def tearDown(self):
        self.app.extensions["ledger"].db.close()
        self.tmp.cleanup()

    def test_success_creates_secure_workflow_cookie(self):
        response = self.client.post(
            "/api/experiments/led/control",
            json={"action": "OFF"},
            headers=self.origin,
        )

        self.assertEqual(response.status_code, 200, response.json)

        cookie = response.headers.get("Set-Cookie", "")
        self.assertIn("sentinel_workstation_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_successful_requests_reuse_session(self):
        first = self.client.post(
            "/api/experiments/led/control",
            json={"action": "OFF"},
            headers=self.origin,
        )
        second = self.client.post(
            "/api/experiments/led/control",
            json={"action": "OFF"},
            headers=self.origin,
        )

        self.assertEqual(first.status_code, 200, first.json)
        self.assertEqual(second.status_code, 200, second.json)

        sessions = self.app.extensions["workstation_sessions"]._sessions
        self.assertEqual(len(sessions), 1)

    def test_workstation_cookie_does_not_grant_admin_authority(self):
        response = self.client.post(
            "/api/experiments/led/control",
            json={"action": "OFF"},
            headers=self.origin,
        )
        self.assertEqual(response.status_code, 200, response.json)

        admin = self.client.post(
            "/api/admin/recovery",
            json={"action": "RESET"},
            headers=self.origin,
        )

        self.assertEqual(admin.status_code, 401)

    def test_rejected_request_does_not_orphan_sessions(self):
        first = self.client.post(
            "/api/experiments/led/control",
            json={"action": "ON"},
            headers=self.origin,
        )
        second = self.client.post(
            "/api/experiments/led/control",
            json={"action": "ON"},
            headers=self.origin,
        )

        self.assertEqual(first.status_code, 409, first.json)
        self.assertEqual(second.status_code, 409, second.json)

        sessions = self.app.extensions["workstation_sessions"]._sessions
        self.assertEqual(len(sessions), 1)


if __name__ == "__main__":
    unittest.main()
