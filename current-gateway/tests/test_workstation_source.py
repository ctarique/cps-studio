import tempfile
import unittest
from pathlib import Path

from gateway.app import create_app
from gateway.config import Config
from gateway.simulator import Simulator


SOURCE = """void experiment() {
  led(1);
  wait_ms(500);
  led(0);
  status();
}"""


class WorkstationSourceTests(unittest.TestCase):
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

    def submit(self):
        return self.client.post(
            "/api/submissions",
            json={
                "source": SOURCE,
                "experiment": "led-status-v1",
            },
            headers=self.origin,
        )

    def test_submission_requires_no_student_token_or_identity(self):
        response = self.submit()

        self.assertEqual(response.status_code, 201, response.json)

        rid = response.json["run_id"]
        submission = self.app.extensions["ledger"].submission(rid)

        self.assertEqual(
            submission["access_model"],
            "workstation_session",
        )
        self.assertRegex(
            submission["owner_ref"],
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(
            submission["owner_ref"],
            submission["token_id"],
        )

    def test_same_workstation_session_can_read_its_run(self):
        response = self.submit()
        self.assertEqual(response.status_code, 201, response.json)

        rid = response.json["run_id"]

        details = self.client.get("/api/runs/" + rid)

        self.assertEqual(details.status_code, 200, details.json)
        self.assertEqual(details.json["run_id"], rid)

    def test_other_workstation_session_cannot_read_run(self):
        response = self.submit()
        self.assertEqual(response.status_code, 201, response.json)

        rid = response.json["run_id"]

        other = self.app.test_client()
        details = other.get("/api/runs/" + rid)

        self.assertEqual(details.status_code, 404, details.json)

    def test_admin_review_contains_workstation_metadata_not_identity(self):
        response = self.submit()
        self.assertEqual(response.status_code, 201, response.json)

        rid = response.json["run_id"]

        review = self.client.get(
            "/api/admin/runs/" + rid + "/review",
            headers={"X-Sentinel-Token": self.cfg.admin_token},
        )

        self.assertEqual(review.status_code, 200, review.json)
        self.assertEqual(
            review.json["access_model"],
            "workstation_session",
        )
        self.assertRegex(
            review.json["owner_ref"],
            r"^[0-9a-f]{64}$",
        )
        self.assertNotIn("student", review.json)
        self.assertNotIn("token", review.json)


if __name__ == "__main__":
    unittest.main()
