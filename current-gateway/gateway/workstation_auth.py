"""Temporary workstation workflow sessions.

These sessions provide browser workflow ownership only. They do not identify a
student, authenticate an instructor, or grant Raspberry Pi administrative access.
"""

import hashlib
import secrets
import threading
import time


class WorkstationSessions:
    cookie_name = "sentinel_workstation_session"
    ttl = 4 * 60 * 60
    max_sessions = 128

    def __init__(self):
        self.clock = time.monotonic
        self._sessions = {}
        self._lock = threading.RLock()

    def _prune(self):
        now = self.clock()
        self._sessions = {
            sid: record
            for sid, record in self._sessions.items()
            if record["expires"] > now
        }

    @staticmethod
    def _valid_sid(sid):
        return (
            isinstance(sid, str)
            and len(sid) == 43
            and sid.isascii()
            and all(c.isalnum() or c in "_-" for c in sid)
        )

    def create(self, origin, previous=None):
        with self._lock:
            self._prune()

            if previous:
                self._sessions.pop(previous, None)

            if len(self._sessions) >= self.max_sessions:
                return None

            sid = secrets.token_urlsafe(32)
            owner_ref = hashlib.sha256(sid.encode("ascii")).hexdigest()

            self._sessions[sid] = {
                "owner_ref": owner_ref,
                "origin": origin,
                "expires": self.clock() + self.ttl,
            }

            return sid

    def get(self, sid, origin):
        with self._lock:
            self._prune()

            if not self._valid_sid(sid):
                return None

            record = self._sessions.get(sid)
            if not record or record["origin"] != origin:
                return None

            return dict(record)

    def revoke(self, sid):
        with self._lock:
            self._sessions.pop(sid, None)
