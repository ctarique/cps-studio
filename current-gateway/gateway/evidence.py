"""Transactional, append-only event history. Not tamper proof against the OS administrator."""
import json
from contextlib import contextmanager
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

class EvidenceError(RuntimeError):
    pass

def utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

class Evidence:
    def __init__(self, config):
        self.config = config
        self._recovery_active = False
        self._recovery_remaining = 0
        config.data_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.db = sqlite3.connect(config.data_dir/"evidence.sqlite3",check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, state TEXT NOT NULL,
            config_ref TEXT NOT NULL, source TEXT, program TEXT, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS submission_contacts(run_id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS run_submissions(run_id TEXT PRIMARY KEY,
            token_id TEXT NOT NULL, experiment TEXT NOT NULL, device_id TEXT NOT NULL,
            source_sha256 TEXT, program_sha256 TEXT, policy_ref TEXT NOT NULL,
            reasons TEXT NOT NULL, exception_eligible INTEGER NOT NULL,
            source_available INTEGER NOT NULL, created TEXT NOT NULL,
            owner_ref TEXT, access_model TEXT);
        CREATE TABLE IF NOT EXISTS exception_requests(run_id TEXT PRIMARY KEY,
            requested_at TEXT NOT NULL, decided_at TEXT, decision TEXT);
        CREATE TRIGGER IF NOT EXISTS immutable_submission_update BEFORE UPDATE ON run_submissions
            BEGIN SELECT RAISE(ABORT,'immutable submission'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_submission_delete BEFORE DELETE ON run_submissions
            BEGIN SELECT RAISE(ABORT,'immutable submission'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_run_source BEFORE UPDATE OF source ON runs
            WHEN OLD.source IS NOT NULL AND NEW.source IS NOT OLD.source
            BEGIN SELECT RAISE(ABORT,'immutable source'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_run_program BEFORE UPDATE OF program ON runs
            WHEN OLD.program IS NOT NULL AND NEW.program IS NOT OLD.program
            BEGIN SELECT RAISE(ABORT,'immutable program'); END;
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, run_id TEXT NOT NULL,
            time TEXT NOT NULL, class TEXT NOT NULL, outcome TEXT NOT NULL,
            config_ref TEXT NOT NULL, mode TEXT NOT NULL, detail TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS immutable_events_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT,'append only'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_events_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT,'append only'); END;
        CREATE TABLE IF NOT EXISTS recovery_event_seqs(seq INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS recovery_run_ids(id TEXT PRIMARY KEY);
        CREATE TRIGGER IF NOT EXISTS immutable_recovery_events_update BEFORE UPDATE ON recovery_event_seqs
            BEGIN SELECT RAISE(ABORT,'append only capacity attribution'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_recovery_events_delete BEFORE DELETE ON recovery_event_seqs
            BEGIN SELECT RAISE(ABORT,'append only capacity attribution'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_recovery_runs_update BEFORE UPDATE ON recovery_run_ids
            BEGIN SELECT RAISE(ABORT,'append only capacity attribution'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_recovery_runs_delete BEFORE DELETE ON recovery_run_ids
            BEGIN SELECT RAISE(ABORT,'append only capacity attribution'); END;
        """)

        # Schema 1.0.3 adds neutral workflow ownership without rewriting
        # historical immutable submission records.
        columns = {
            row["name"]
            for row in self.db.execute("PRAGMA table_info(run_submissions)")
        }
        if "owner_ref" not in columns:
            self.db.execute(
                "ALTER TABLE run_submissions ADD COLUMN owner_ref TEXT"
            )
        if "access_model" not in columns:
            self.db.execute(
                "ALTER TABLE run_submissions ADD COLUMN access_model TEXT"
            )

        self.db.commit()
    def regular_capacity_available(self, required_events=1):
        events = self.db.execute(
            "SELECT count(*) FROM events WHERE seq NOT IN (SELECT seq FROM recovery_event_seqs)"
        ).fetchone()[0]
        runs = self.db.execute(
            "SELECT count(*) FROM runs WHERE id NOT IN (SELECT id FROM recovery_run_ids)"
        ).fetchone()[0]
        return (events + required_events <= self.config.max_events
                and runs < self.config.max_runs)

    @contextmanager
    def recovery_capacity(self, required_events):
        # Only the authenticated instructor LOCK_STOP/RESET handler selects
        # this scope. The same durable ledger, transactions and triggers apply.
        # A second bounded pool equal to the configured ordinary quotas is
        # reserved for recovery; ordinary requests cannot spend this pool.
        if (self._recovery_active or type(required_events) is not int
                or not 1 <= required_events <= self.config.max_events):
            raise EvidenceError("RECOVERY_CAPACITY")
        events = self.db.execute("SELECT count(*) FROM recovery_event_seqs").fetchone()[0]
        runs = self.db.execute("SELECT count(*) FROM recovery_run_ids").fetchone()[0]
        if (events + required_events > self.config.max_events
                or runs >= self.config.max_runs):
            raise EvidenceError("RECOVERY_CAPACITY")
        self._recovery_active = True
        self._recovery_remaining = required_events
        try:
            yield
        finally:
            self._recovery_active = False
            self._recovery_remaining = 0

    def event(self, rid, category, outcome, **detail):
        if self._recovery_active:
            if self._recovery_remaining <= 0:
                raise EvidenceError("RECOVERY_CAPACITY")
            detail["audit_capacity"] = "recovery_reserve"
        elif self.db.execute(
                "SELECT count(*) FROM events WHERE seq NOT IN (SELECT seq FROM recovery_event_seqs)"
        ).fetchone()[0] >= self.config.max_events:
            raise EvidenceError("EVIDENCE_CAPACITY")
        cursor = self.db.execute(
            "INSERT INTO events(run_id,time,class,outcome,config_ref,mode,detail) VALUES(?,?,?,?,?,?,?)",
            (rid,utc(),category,outcome,self.config.reference,self.config.mode,json.dumps(detail,sort_keys=True))
        )
        if self._recovery_active:
            self.db.execute("INSERT INTO recovery_event_seqs(seq) VALUES(?)",(cursor.lastrowid,))
            self._recovery_remaining -= 1

    def create(self,rid,state="REJECTED",source=None):
        if self._recovery_active:
            if self.db.execute("SELECT count(*) FROM recovery_run_ids").fetchone()[0] >= self.config.max_runs:
                raise EvidenceError("RECOVERY_CAPACITY")
        elif self.db.execute(
                "SELECT count(*) FROM runs WHERE id NOT IN (SELECT id FROM recovery_run_ids)"
        ).fetchone()[0] >= self.config.max_runs:
            raise EvidenceError("RUN_CAPACITY")
        self.db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)",
                        (rid,state,self.config.reference,source,None,utc()))
        if self._recovery_active:
            self.db.execute("INSERT INTO recovery_run_ids(id) VALUES(?)",(rid,))
    def run(self,rid):
        row=self.db.execute("SELECT * FROM runs WHERE id=?",(rid,)).fetchone()
        return dict(row) if row else None
    def record_submission(
            self,rid,token_id,experiment,device_id,source_hash,program_hash,
            policy_ref,reasons,eligible,source_available,
            owner_ref=None,access_model=None):
        if not owner_ref:
            raise EvidenceError("OWNER_REF_REQUIRED")
        if not access_model:
            raise EvidenceError("ACCESS_MODEL_REQUIRED")

        self.db.execute("""
            INSERT INTO run_submissions
                (run_id,token_id,experiment,device_id,source_sha256,program_sha256,
                 policy_ref,reasons,exception_eligible,source_available,created,
                 owner_ref,access_model)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            (rid,token_id,experiment,device_id,source_hash,program_hash,policy_ref,
             json.dumps(reasons),int(eligible),int(source_available),utc(),
             owner_ref,access_model))
    def submission(self,rid):
        row=self.db.execute("SELECT * FROM run_submissions WHERE run_id=?",(rid,)).fetchone()
        if not row:return None
        item=dict(row);item["reasons"]=json.loads(item["reasons"])
        item["exception_eligible"]=bool(item["exception_eligible"])
        item["source_available"]=bool(item["source_available"])

        # Historical rows predate neutral workflow ownership. Interpret them
        # without rewriting immutable evidence.
        if not item.get("owner_ref"):
            item["owner_ref"]=item["token_id"]
        if not item.get("access_model"):
            item["access_model"]="legacy_student_token"

        return item
    def request_exception(self,rid):
        self.db.execute("INSERT INTO exception_requests(run_id,requested_at) VALUES(?,?)",(rid,utc()))
    def decide_exception(self,rid,decision):
        self.db.execute("UPDATE exception_requests SET decided_at=?,decision=? WHERE run_id=?",(utc(),decision,rid))
    def state(self,rid,state,program=None):
        self.db.execute("UPDATE runs SET state=?, program=COALESCE(?,program) WHERE id=?",(state,program,rid))
    def export(self,rid):
        run=self.run(rid)
        if not run:return None
        run.pop("source");run.pop("program")
        events=[{**dict(r),"detail":json.loads(r["detail"])} for r in self.db.execute("SELECT * FROM events WHERE run_id=? ORDER BY seq",(rid,))]
        return {"run":run,"events":events,"physical_validation":"UNVALIDATED",
                "limitation":"Reference attachment or device reports do not establish physical behavior."}
