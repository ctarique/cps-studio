"""Bounded process-local administrator sessions; no credentials are retained."""
import hmac
import secrets
import threading
import time

class AdminSessions:
    cookie_name = "sentinel_admin_session"
    ttl = 1200
    max_sessions = 64

    def __init__(self):
        self.clock = time.monotonic
        self._sessions = {}
        self._attempts = {}
        self._lock = threading.RLock()

    def _prune(self):
        now = self.clock()
        self._sessions = {k:v for k,v in self._sessions.items() if v["expires"] > now}
        self._attempts = {k:v for k,v in self._attempts.items() if v[0] > now - 60}

    def allow_attempt(self, address):
        with self._lock:
            self._prune()
            now = self.clock()
            attempts = self._attempts.get(address)
            if attempts is None:
                if len(self._attempts) >= 128:
                    return False
                attempts = [now, 0]
                self._attempts[address] = attempts
            if attempts[1] >= 10:
                return False
            attempts[1] += 1
            return True

    def create(self, origin, previous=None):
        with self._lock:
            self._prune()
            if previous:
                self._sessions.pop(previous, None)
            if len(self._sessions) >= self.max_sessions:
                return None
            sid = secrets.token_urlsafe(32)
            record = {"csrf":secrets.token_hex(32), "expires":self.clock()+self.ttl,
                      "origin":origin}
            self._sessions[sid] = record
            return sid

    def get(self, sid, origin):
        with self._lock:
            self._prune()
            if not isinstance(sid, str) or len(sid) != 43:
                return None
            record = self._sessions.get(sid)
            if not record or record["origin"] != origin:
                return None
            return dict(record)

    def authorized(self, sid, origin, csrf):
        record = self.get(sid, origin)
        return bool(record and isinstance(csrf, str) and len(csrf) == 64
                    and csrf.isascii() and hmac.compare_digest(record["csrf"], csrf))

    def revoke(self, sid):
        with self._lock:
            self._sessions.pop(sid, None)
