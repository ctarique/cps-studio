
"""Phase 1: durable bounded instructor recovery after ordinary quota exhaustion."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from gateway.app import create_app
from gateway.config import Config
from gateway.simulator import Simulator
from gateway.evidence import EvidenceError

class RecoveryReserveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg=Config(data_dir=Path(self.tmp.name),admin_token="2"*64,device_key="3"*64,max_events=100,max_runs=2)
        self.sim=Simulator()
        self.app=create_app(self.cfg,self.sim)
        self.client=self.app.test_client()
        self.ledger=self.app.extensions["ledger"]
        self.addCleanup(self.ledger.db.close)
        self.admin={"Origin":"http://localhost","X-Sentinel-Token":self.cfg.admin_token}
    def exhaust(self,degrade=True):
        for _ in range(101 if degrade else 100):
            self.assertEqual(self.client.get("/api/admin/devices").status_code,401)
    def recover(self,action="LOCK_STOP",headers=None):
        return self.client.post("/api/admin/recovery",json={"action":action},headers=headers or self.admin)
    def events(self,rid):
        return self.ledger.export(rid)["events"]
    def test_audit_unauthorized_quota_fixture_recovery_is_durable(self):
        self.exhaust()
        r=self.recover()
        self.assertEqual(r.status_code,200,r.json)
        self.assertTrue(r.json["locked"])
        self.assertEqual(r.json["audit_logging"],"RECOVERY_ONLY")
        self.assertTrue(self.app.extensions["workflow"]["degraded"])
        events=self.events(r.json["run_id"])
        self.assertTrue(any(e["outcome"]=="DISPATCH_INTENT" for e in events))
        self.assertTrue(any(e["outcome"]=="LOCAL_RESULT" for e in events))
        self.assertTrue(all(e["detail"]["audit_capacity"]=="recovery_reserve" for e in events))
        self.assertEqual(self.ledger.db.execute("SELECT count(*) FROM events WHERE outcome='REJECTED'").fetchone()[0],100)
    def test_full_quota_without_previous_degradation_selects_reserve(self):
        self.exhaust(False)
        self.assertFalse(self.app.extensions["workflow"]["degraded"])
        self.assertEqual(self.recover("RESET").status_code,200)
        self.assertTrue(self.app.extensions["workflow"]["locked"])
    def test_run_quota_also_has_bounded_recovery_capacity(self):
        self.ledger.create("1"*32)
        self.ledger.create("4"*32)
        self.ledger.db.commit()
        self.assertEqual(self.recover().status_code,200)
        self.assertEqual(self.ledger.db.execute("SELECT count(*) FROM runs").fetchone()[0],3)
        with self.assertRaises(EvidenceError):
            self.ledger.create("5"*32)
    def test_reserved_capacity_exhaustion_refuses_before_transport(self):
        self.exhaust()
        with self.ledger.recovery_capacity(required_events=100):
            for _ in range(100):
                self.ledger.event("1"*32,"recovery","TEST_FIXTURE")
            self.ledger.db.commit()
        with patch.object(self.sim,"command",wraps=self.sim.command) as command:
            r=self.recover()
        self.assertEqual(r.status_code,503,r.json)
        command.assert_not_called()
        self.assertTrue(self.app.extensions["workflow"]["locked"])
    def test_reserve_requires_room_for_complete_attempt(self):
        self.exhaust()
        with self.ledger.recovery_capacity(required_events=90):
            for _ in range(90):
                self.ledger.event("1"*32,"recovery","TEST_FIXTURE")
            self.ledger.db.commit()
        with patch.object(self.sim,"command",wraps=self.sim.command) as command:
            r=self.recover()
        self.assertEqual(r.status_code,503)
        command.assert_not_called()
    def test_underlying_storage_failure_refuses_before_transport(self):
        self.exhaust()
        with patch.object(self.ledger,"event",side_effect=sqlite3.OperationalError("synthetic storage failure")), patch.object(self.sim,"command",wraps=self.sim.command) as command:
            r=self.recover()
        self.assertEqual(r.status_code,503)
        command.assert_not_called()
    def test_full_quota_does_not_allow_unlock_or_workstation_off(self):
        self.exhaust()
        with patch.object(self.sim,"command",wraps=self.sim.command) as command:
            self.assertEqual(self.recover("UNLOCK").status_code,503)
            off=self.client.post("/api/experiments/led/control",json={"action":"OFF"},headers={"Origin":"http://localhost"})
            self.assertEqual(off.status_code,503)
        command.assert_not_called()
    def test_reserve_does_not_weaken_authentication_origin_or_csrf(self):
        self.exhaust()
        with patch.object(self.sim,"command",wraps=self.sim.command) as command:
            self.assertEqual(self.recover(headers={"Origin":"http://localhost"}).status_code,401)
            self.assertEqual(self.recover(headers={"Origin":"https://untrusted.invalid","X-Sentinel-Token":self.cfg.admin_token}).status_code,403)
            # Browser instructor session still requires the independent CSRF value.
            login=self.client.post("/api/admin/session",json={},headers=self.admin)
            self.assertEqual(login.status_code,200)
            self.assertEqual(self.recover(headers={"Origin":"http://localhost"}).status_code,401)
        command.assert_not_called()
    def test_reserve_scope_does_not_leak_into_subsequent_mutations(self):
        self.exhaust()
        self.assertEqual(self.recover().status_code,200)
        with self.assertRaises(EvidenceError):
            self.ledger.event("1"*32,"workflow","TEST_FIXTURE")
        self.assertEqual(self.recover("UNLOCK").status_code,503)
    def test_restart_remains_locked_and_recovery_history_exportable(self):
        self.exhaust()
        r=self.recover()
        self.assertEqual(r.status_code,200,r.json)
        rid=r.json["run_id"]
        self.ledger.db.close()
        self.app=create_app(self.cfg,Simulator())
        self.ledger=self.app.extensions["ledger"]
        self.addCleanup(self.ledger.db.close)
        self.client=self.app.test_client()
        self.assertTrue(self.app.extensions["workflow"]["locked"])
        exported=self.client.get("/api/admin/runs/"+rid+"/evidence",headers=self.admin)
        self.assertEqual(exported.status_code,200)
        self.assertTrue(any(e["outcome"]=="DISPATCH_INTENT" for e in exported.json["events"]))

if __name__=="__main__":unittest.main()
