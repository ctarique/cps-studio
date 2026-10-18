"""Successor regressions using an authenticated local HTTP simulator only."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from gateway.app import create_app
from gateway.config import Config
from gateway.evidence import EvidenceError
from gateway.simulator import Simulator, make_server
from gateway.transport import HTTPTransport, TransportError


SOURCE = "void experiment(){led(1);wait_ms(1000);led(0);}"


class BackendReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = [100.0]
        self.sim = Simulator(clock=lambda: self.now[0])
        self.server = make_server("3" * 64, sim=self.sim)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cfg = Config(data_dir=Path(self.tmp.name), admin_token="2" * 64,
                          device_key="3" * 64, mode="simulator_http",
                          device_port=self.server.server_port)
        self.transport = HTTPTransport(self.cfg)
        self.app = create_app(self.cfg, self.transport)
        self.client = self.app.test_client()
        self.other = self.app.test_client()
        self.origin = {"Origin": "http://localhost"}
        self.admin = {**self.origin, "X-Sentinel-Token": self.cfg.admin_token}
        self.ledger = self.app.extensions["ledger"]
        self.display = self.app.extensions["lab_display"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.ledger.db.close()
        self.tmp.cleanup()

    def recovery(self, action):
        return self.client.post("/api/admin/recovery", json={"action": action}, headers=self.admin)

    def unlock(self):
        response = self.recovery("UNLOCK")
        self.assertEqual(response.status_code, 200, response.json)
        self.assertFalse(response.json["locked"])

    def test_unlock_does_not_require_device_status(self):
        with patch.object(
            self.transport,
            "status",
            side_effect=TransportError("TRANSPORT_UNAVAILABLE")
        ) as status:
            response = self.recovery("UNLOCK")
        self.assertEqual(response.status_code, 200, response.json)
        self.assertFalse(response.json["locked"])
        self.assertFalse(response.json["response_available"])
        status.assert_not_called()

    def test_unlocked_gateway_still_blocks_unavailable_device_execution(self):
        self.unlock()
        rid = self.submit()
        before = self.sim.seq
        with patch.object(
            self.transport,
            "command",
            side_effect=TransportError("TRANSPORT_UNAVAILABLE", True)
        ):
            response = self.execute(rid)
        self.assertEqual(response.status_code, 502)
        self.assertTrue(self.app.extensions["workflow"]["locked"])
        self.assertEqual(self.sim.seq, before)

    def submit(self):
        response = self.client.post("/api/submissions", json={"source": SOURCE, "experiment": "led-status-v1"}, headers=self.origin)
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["run_id"]

    def execute(self, rid):
        return self.client.post(f"/api/runs/{rid}/execute", json={}, headers=self.origin)

    def prepare_display(self, client=None, headers=None):
        return (client or self.client).post("/api/display/prepare", json={"experiment": "led-status-v1"}, headers=headers or self.origin)

    def guided(self, action, client=None):
        return (client or self.client).post("/api/experiments/led/control", json={"action": action}, headers=self.origin)

    def test_recovery_invalidates_all_pending_led_authority(self):
        for action in ("LOCK_STOP", "RESET", "UNLOCK"):
            with self.subTest(action=action):
                self.unlock()
                rid = self.submit()
                self.assertEqual(self.recovery(action).status_code, 200)
                self.assertEqual(self.ledger.run(rid)["state"], "INVALIDATED")
                self.unlock()
                self.assertFalse(self.client.get(f"/api/runs/{rid}").json["can_run"])
                self.assertEqual(self.execute(rid).status_code, 409)

    def test_check_while_locked_requires_fresh_check_after_unlock(self):
        rid = self.submit()
        self.unlock()
        self.assertEqual(self.ledger.run(rid)["state"], "INVALIDATED")
        fresh = self.submit()
        self.assertTrue(self.client.get(f"/api/runs/{fresh}").json["can_run"])

    def test_status_communication_failure_invalidates_pending_authority(self):
        self.unlock()
        rid = self.submit()
        with patch.object(self.transport, "status", side_effect=TransportError("TRANSPORT_UNAVAILABLE")):
            failed = self.client.post(f"/api/runs/{rid}/status", json={}, headers=self.origin)
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(self.ledger.run(rid)["state"], "INVALIDATED")
        self.unlock()
        self.assertEqual(self.execute(rid).status_code, 409)

    def test_busy_preserves_ready_without_dispatch_or_lock(self):
        self.unlock()
        self.assertEqual(self.guided("ON").status_code, 200)
        rid = self.submit()
        before = self.sim.seq
        response = self.execute(rid)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["error"], "DEVICE_BUSY")
        self.assertEqual(self.sim.seq, before)
        self.assertFalse(self.app.extensions["workflow"]["locked"])
        self.assertEqual(self.ledger.run(rid)["state"], "READY_TO_RUN")

    def test_guided_off_links_original_run_without_fabricating_command_identity(self):
        self.unlock()
        self.assertEqual(self.prepare_display().status_code, 200)
        on = self.guided("ON")
        original = on.json["run_id"]
        pending = self.submit()
        off = self.guided("OFF", self.other)
        self.assertEqual(off.status_code, 200, off.json)
        command = off.json["run_id"]
        self.assertNotEqual(command, original)
        self.assertEqual(self.sim.rid, command)
        self.assertEqual(off.json.get("stopped_run_id"), original)
        self.assertEqual(self.ledger.run(original)["state"], "DEVICE_REPORTED_COMPLETE")
        self.assertEqual(self.ledger.run(pending)["state"], "INVALIDATED")
        self.assertEqual(self.display.snapshot()["mode"], "LED_COMPLETE")
        self.assertFalse(self.app.extensions["workflow"]["locked"])
        original_events = self.ledger.export(original)["events"]
        self.assertTrue(any(e["detail"].get("stop_command_id") == command for e in original_events))
        command_events = self.ledger.export(command)["events"]
        self.assertTrue(any(e["detail"].get("stopped_run_id") == original for e in command_events))

    def test_guided_off_unknown_prior_identity_does_not_close_unrelated_run(self):
        self.unlock()
        original = self.guided("ON").json["run_id"]
        self.sim.rid = "f" * 32
        off = self.guided("OFF")
        self.assertEqual(off.status_code, 200)
        self.assertIsNone(off.json.get("stopped_run_id"))
        self.assertEqual(self.ledger.run(original)["state"], "DEVICE_REPORTED")

    def test_guided_off_unconfirmed_does_not_close_original(self):
        self.unlock()
        original = self.guided("ON").json["run_id"]
        with patch.object(self.transport, "command", side_effect=TransportError("TRANSPORT_UNAVAILABLE", True)):
            off = self.guided("OFF")
        self.assertEqual(off.status_code, 502)
        self.assertEqual(self.ledger.run(original)["state"], "DEVICE_REPORTED")
        self.assertTrue(self.app.extensions["workflow"]["locked"])

    def test_custom_terminal_status_closes_original_and_display(self):
        self.unlock()
        self.assertEqual(self.prepare_display().status_code, 200)
        rid = self.submit()
        self.assertEqual(self.execute(rid).status_code, 200)
        self.now[0] += 2
        status = self.client.post(f"/api/runs/{rid}/status", json={}, headers=self.origin)
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json["current_device_run"])
        self.assertEqual(status.json.get("state"), "DEVICE_REPORTED_COMPLETE")
        self.assertEqual(self.ledger.run(rid)["state"], "DEVICE_REPORTED_COMPLETE")
        self.assertEqual(self.display.snapshot()["mode"], "LED_COMPLETE")
        self.assertEqual(self.execute(rid).status_code, 409)

    def test_display_home_rejects_non_owner(self):
        self.unlock()
        self.assertEqual(self.prepare_display().status_code, 200)
        response = self.other.post("/api/display/home", json={}, headers=self.origin)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["error"], "DISPLAY_IN_USE")

    def test_display_home_and_prepare_reject_active_execution(self):
        self.unlock()
        self.assertEqual(self.prepare_display().status_code, 200)
        self.assertEqual(self.guided("ON").status_code, 200)
        home = self.client.post("/api/display/home", json={}, headers=self.origin)
        self.assertEqual(home.status_code, 409)
        prepared = self.prepare_display()
        self.assertEqual(prepared.status_code, 409)
        self.assertEqual(self.display.snapshot()["mode"], "LED_RUNNING")
        self.assertEqual(self.sim.state, "RUNNING")

    def test_instructor_display_override_does_not_stop_active_device(self):
        self.unlock()
        self.assertEqual(self.guided("ON").status_code, 200)
        before = self.sim.seq
        response = self.client.post("/api/display/state", json={"mode": "READY"}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sim.seq, before)
        self.assertEqual(self.sim.state, "RUNNING")
        response = self.prepare_display(self.other)
        self.assertEqual(response.status_code, 409)

    def test_display_prepare_rejects_owner_during_active_execution(self):
        self.unlock()
        self.assertEqual(self.prepare_display().status_code, 200)
        self.assertEqual(self.guided("ON").status_code, 200)
        response = self.prepare_display()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["error"], "DISPLAY_IN_USE")
        self.assertEqual(self.display.snapshot()["mode"], "LED_RUNNING")

    def test_startup_invalidates_pending_authority(self):
        self.unlock()
        rid = self.submit()
        second = create_app(self.cfg, self.transport)
        try:
            self.assertEqual(second.extensions["ledger"].run(rid)["state"], "INVALIDATED")
            self.assertTrue(second.extensions["workflow"]["locked"])
        finally:
            second.extensions["ledger"].db.close()

    def test_uncertain_dispatch_consumes_attempt_and_invalidates_other_pending(self):
        self.unlock()
        rid = self.submit()
        pending = self.submit()
        original = self.transport.command
        def lose_result(*args, **kwargs):
            original(*args, **kwargs)
            raise TransportError("TRANSPORT_UNAVAILABLE", True)
        with patch.object(self.transport, "command", side_effect=lose_result):
            result = self.execute(rid)
        self.assertEqual(result.status_code, 502)
        self.assertEqual(self.ledger.run(rid)["state"], "INCOMPLETE")
        self.assertEqual(self.ledger.run(pending)["state"], "INVALIDATED")
        self.assertTrue(self.app.extensions["workflow"]["locked"])
        self.assertEqual(self.recovery("RESET").status_code, 200)
        self.unlock()
        self.assertEqual(self.execute(rid).status_code, 409)

    def test_validation_rejection_does_not_invalidate_other_pending(self):
        self.unlock()
        rid = self.submit()
        before = self.sim.seq
        response = self.client.post("/api/submissions", json={"source": "invalid", "experiment": "led-status-v1"}, headers=self.origin)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.ledger.run(rid)["state"], "READY_TO_RUN")
        self.assertEqual(self.sim.seq, before)
        self.assertFalse(self.app.extensions["workflow"]["locked"])

    def test_run_stop_invalidates_pending_and_remains_single_use(self):
        self.unlock()
        rid = self.submit()
        self.assertEqual(self.execute(rid).status_code, 200)
        pending = self.submit()
        response = self.client.post(f"/api/runs/{rid}/stop", json={}, headers=self.origin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.ledger.run(pending)["state"], "INVALIDATED")
        self.assertTrue(self.app.extensions["workflow"]["locked"])
        status = self.client.post(f"/api/runs/{rid}/status", json={}, headers=self.origin)
        self.assertEqual(status.json["state"], "DEVICE_REPORTED_COMPLETE")
        self.unlock()
        self.assertEqual(self.execute(rid).status_code, 409)

    def test_preflight_evidence_failure_prevents_dispatch_and_unlock(self):
        self.unlock()
        rid = self.submit()
        before = self.sim.seq
        original = self.ledger.event
        def fail_preflight(rid, category, outcome, **detail):
            if category == "simulated_device_preflight":
                raise EvidenceError("TEST_EVIDENCE_UNAVAILABLE")
            return original(rid, category, outcome, **detail)
        with patch.object(self.ledger, "event", side_effect=fail_preflight):
            response = self.execute(rid)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.sim.seq, before)
        self.assertTrue(self.app.extensions["workflow"]["degraded"])
        self.assertEqual(self.recovery("UNLOCK").status_code, 503)

    def test_authenticated_preflight_is_retained_without_private_fields(self):
        self.unlock()
        rid = self.submit()
        self.assertEqual(self.execute(rid).status_code, 200)
        events = self.ledger.export(rid)["events"]
        before = next(e for e in events if e["class"] == "simulated_device_preflight")
        after = next(e for e in events if e["class"] == "simulated_device_response")
        self.assertLess(before["seq"], after["seq"])
        self.assertEqual(before["detail"]["state"], "IDLE")
        self.assertEqual(before["detail"]["led_reported"], 0)
        self.assertEqual(before["detail"]["origin"], "SIMULATOR")
        self.assertFalse({"boot", "next_seq", "device_host", "device_key"} & set(before["detail"]))

    def test_instructor_cannot_replace_locked_setup_via_presentation_endpoints(self):
        for path, data in (("/api/display/prepare", {"experiment": "led-status-v1"}),
                           ("/api/display/track", {"track_id": "straight"}),
                           ("/api/display/idle", {})):
            with self.subTest(path=path):
                self.display.recovery()
                response = self.client.post(path, json=data, headers=self.admin)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json["error"], "GATEWAY_LOCKED")
                self.assertEqual(self.display.snapshot()["mode"], "RECOVERY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
