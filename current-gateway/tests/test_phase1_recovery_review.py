"""Independent quota-recovery review regressions; synthetic stores/devices only."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from gateway.app import create_app
from gateway.config import Config
from gateway.evidence import Evidence, EvidenceError
from gateway.simulator import Simulator
from gateway.transport import TransportError


class RecoveryIndependentReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(data_dir=Path(self.tmp.name), admin_token="2" * 64,
                          device_key="3" * 64, max_events=100, max_runs=20)
        self.sim = Simulator()
        self.app = create_app(self.cfg, self.sim)
        self.client = self.app.test_client()
        self.ledger = self.app.extensions["ledger"]
        self.admin = {"Origin": "http://localhost", "X-Sentinel-Token": self.cfg.admin_token}
        self.origin = {"Origin": "http://localhost"}

    def tearDown(self):
        self.ledger.db.close()
        self.tmp.cleanup()

    def fill_ordinary_events(self, target=100):
        while self.ledger.db.execute(
            "SELECT count(*) FROM events WHERE seq NOT IN (SELECT seq FROM recovery_event_seqs)"
        ).fetchone()[0] < target:
            self.ledger.event("0" * 32, "review_fixture", "SYNTHETIC")
        self.ledger.db.commit()

    def recover(self, action="LOCK_STOP"):
        return self.client.post("/api/admin/recovery", json={"action": action}, headers=self.admin)

    def recovery_run(self):
        return dict(self.ledger.db.execute(
            "SELECT * FROM runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone())

    def test_near_full_quota_reserves_complete_attempt_before_dispatch(self):
        self.fill_ordinary_events(95)
        result = self.recover()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json["audit_logging"], "RECOVERY_ONLY")
        self.assertEqual(self.sim.seq, 2)
        self.assertEqual(self.ledger.run(result.json["run_id"])["state"], "RECOVERY_RECORDED")
        self.assertTrue(self.app.extensions["workflow"]["degraded"])

    def test_post_dispatch_storage_failure_leaves_explicit_interrupted_identity(self):
        self.fill_ordinary_events()
        original_event = self.ledger.event

        def fail_response(rid, category, outcome, **detail):
            if outcome == "RESPONSE_RECEIVED":
                raise sqlite3.OperationalError("synthetic post-dispatch storage failure")
            return original_event(rid, category, outcome, **detail)

        with patch.object(self.ledger, "event", side_effect=fail_response):
            result = self.recover()
        self.assertEqual(result.status_code, 503, result.json)
        self.assertEqual(self.sim.seq, 2, "synthetic STOP really dispatched")
        run = self.recovery_run()
        self.assertIn(run["state"], ("COMMUNICATING", "INCOMPLETE"))
        events = self.ledger.export(run["id"])["events"]
        self.assertTrue(any(e["outcome"] == "DISPATCH_INTENT" for e in events))
        self.assertTrue(any(e["class"] == "simulated_device_preflight" for e in events))
        self.assertFalse(any(e["outcome"] == "LOCAL_RESULT" for e in events))
        self.assertTrue(self.app.extensions["workflow"]["locked"])
        self.assertTrue(self.app.extensions["workflow"]["degraded"])
        self.assertFalse(self.ledger._recovery_active)
        with self.assertRaises(EvidenceError):
            self.ledger.event("0" * 32, "review_fixture", "ORDINARY_CANNOT_USE_RESERVE")

    def test_preflight_storage_failure_dispatches_no_command(self):
        self.fill_ordinary_events()
        original_event = self.ledger.event

        def fail_preflight(rid, category, outcome, **detail):
            if category == "simulated_device_preflight":
                raise sqlite3.OperationalError("synthetic preflight storage failure")
            return original_event(rid, category, outcome, **detail)

        with patch.object(self.ledger, "event", side_effect=fail_preflight):
            result = self.recover()
        self.assertEqual(result.status_code, 503, result.json)
        self.assertEqual(self.sim.seq, 1, "preflight failure must precede mutation")
        run = self.recovery_run()
        events = self.ledger.export(run["id"])["events"]
        self.assertTrue(any(e["outcome"] == "DISPATCH_INTENT" for e in events))
        self.assertFalse(any(e["class"] == "simulated_device_preflight" for e in events))
        self.assertFalse(any(e["outcome"] == "RESPONSE_RECEIVED" for e in events))
        self.assertTrue(self.app.extensions["workflow"]["locked"])
        self.assertFalse(self.ledger._recovery_active)

    def test_uncertain_recovery_preserves_audited_incomplete_result(self):
        self.fill_ordinary_events()
        command = self.sim.command

        def lost_response(*args, **kwargs):
            command(*args, **kwargs)
            raise TransportError("TRANSPORT_UNAVAILABLE", True)

        with patch.object(self.sim, "command", side_effect=lost_response):
            result = self.recover()
        self.assertEqual(result.status_code, 502, result.json)
        self.assertEqual(result.json["audit_logging"], "RECOVERY_ONLY")
        self.assertEqual(self.sim.seq, 2)
        self.assertFalse(result.json["response_available"])
        self.assertEqual(self.ledger.run(result.json["run_id"])["state"], "INCOMPLETE")
        events = self.ledger.export(result.json["run_id"])["events"]
        self.assertTrue(any(e["outcome"] == "UNCERTAIN" for e in events))
        self.assertTrue(any(e["outcome"] == "LOCAL_RESULT" for e in events))
        self.assertFalse(self.ledger._recovery_active)

    def test_complete_budget_accounts_for_all_pending_invalidations(self):
        self.app.extensions["workflow"]["locked"] = False
        pending = []
        for _ in range(12):
            result = self.client.post(
                "/api/submissions",
                json={"source": "void experiment(){status();}", "experiment": "led-status-v1"},
                headers=self.origin,
            )
            self.assertEqual(result.status_code, 201, result.json)
            pending.append(result.json["run_id"])
        self.fill_ordinary_events()
        result = self.recover()
        self.assertEqual(result.status_code, 200, result.json)
        for rid in pending:
            self.assertEqual(self.ledger.run(rid)["state"], "INVALIDATED")
            invalidations = [
                e for e in self.ledger.export(rid)["events"]
                if e["class"] == "authorization" and e["outcome"] == "INVALIDATED"
            ]
            self.assertEqual(len(invalidations), 1)
            self.assertEqual(invalidations[0]["detail"]["initiating_run_id"], result.json["run_id"])
            self.assertEqual(invalidations[0]["detail"]["audit_capacity"], "recovery_reserve")
        self.assertEqual(self.sim.seq, 2)
        self.assertLessEqual(
            self.ledger.db.execute("SELECT count(*) FROM recovery_event_seqs").fetchone()[0],
            12 + 16,
        )

    def test_additive_legacy_schema_migration_preserves_old_records(self):
        legacy_dir = Path(self.tmp.name) / "synthetic-legacy"
        legacy_dir.mkdir()
        old = sqlite3.connect(legacy_dir / "evidence.sqlite3")
        # These are the pre-remediation public ledger columns, with no
        # recovery attribution tables. No real historical records are copied.
        old.executescript("""
            CREATE TABLE runs(id TEXT PRIMARY KEY, state TEXT NOT NULL,
                config_ref TEXT NOT NULL, source TEXT, program TEXT, created TEXT NOT NULL);
            CREATE TABLE events(seq INTEGER PRIMARY KEY, run_id TEXT NOT NULL,
                time TEXT NOT NULL, class TEXT NOT NULL, outcome TEXT NOT NULL,
                config_ref TEXT NOT NULL, mode TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE TRIGGER immutable_events_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT,'append only'); END;
            CREATE TRIGGER immutable_events_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT,'append only'); END;
        """)
        old_run = ("1" * 32, "REJECTED", "SYNTHETIC-OLD-CONFIG", "synthetic old source", "S0",
                   "synthetic-time")
        old_event = (1, "1" * 32, "synthetic-time", "synthetic_fixture", "HISTORICAL_FIXTURE",
                     "SYNTHETIC-OLD-CONFIG", "simulator", '{"synthetic": true}')
        old.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", old_run)
        old.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?)", old_event)
        old.commit()
        old.close()
        cfg = Config(data_dir=legacy_dir, admin_token="2" * 64, device_key="3" * 64,
                     max_events=100, max_runs=20)
        migrated = Evidence(cfg)
        try:
            self.assertEqual(tuple(migrated.db.execute("SELECT * FROM runs").fetchone()), old_run)
            self.assertEqual(tuple(migrated.db.execute("SELECT * FROM events").fetchone()), old_event)
            self.assertEqual(migrated.db.execute("SELECT count(*) FROM recovery_run_ids").fetchone()[0], 0)
            self.assertEqual(migrated.db.execute("SELECT count(*) FROM recovery_event_seqs").fetchone()[0], 0)
            migrated.event("1" * 32, "synthetic_fixture", "NEW_ORDINARY_FIXTURE")
            migrated.db.commit()
            self.assertEqual(migrated.db.execute("SELECT count(*) FROM recovery_event_seqs").fetchone()[0], 0)
            self.assertEqual(migrated.db.execute("PRAGMA synchronous").fetchone()[0], 2)
            self.assertEqual(migrated.db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            with self.assertRaises(sqlite3.IntegrityError):
                migrated.db.execute("DELETE FROM events WHERE seq=1")
            migrated.db.rollback()
            self.assertEqual(tuple(migrated.db.execute("SELECT * FROM events WHERE seq=1").fetchone()), old_event)
        finally:
            migrated.db.close()

    def test_capacity_attribution_and_immutability_remain_consistent(self):
        self.fill_ordinary_events()
        result = self.recover()
        self.assertEqual(result.status_code, 200, result.json)
        seqs = {
            r[0] for r in self.ledger.db.execute("SELECT seq FROM recovery_event_seqs")
        }
        for row in self.ledger.db.execute("SELECT seq,detail FROM events"):
            detail = json.loads(row["detail"])
            self.assertEqual(row["seq"] in seqs, detail.get("audit_capacity") == "recovery_reserve")
        for table in ("recovery_event_seqs", "recovery_run_ids"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.ledger.db.execute("DELETE FROM " + table)
            self.ledger.db.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.db.execute("UPDATE recovery_event_seqs SET seq=999")
        self.ledger.db.rollback()
        self.assertFalse(self.ledger._recovery_active)


if __name__ == "__main__":
    unittest.main()
