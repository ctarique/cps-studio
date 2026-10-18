"""Ephemeral presentation state for the directly connected laboratory display.

The application owns authentication, authorization, evidence and device actions.
This model only correlates presentation updates with its private owner/run.
Public reads expose three allowlisted values and never mutate stored state.
"""
import re
import threading
import time
from types import MappingProxyType


class DisplayError(ValueError):
    pass


RUNNING_TIMEOUT_SECONDS = 10
TRACKS = MappingProxyType({
    "straight": MappingProxyType({"id": "straight", "label": "Track 01 — Straight"}),
    "wide-straight": MappingProxyType({"id": "wide-straight", "label": "Track 02 — Straight Wide"}),
    "curve": MappingProxyType({"id": "curve", "label": "Track 03 — Curve"}),
    "wide-curve": MappingProxyType({"id": "wide-curve", "label": "Track 04 — Curve Wide"}),
    "challenge": MappingProxyType({"id": "challenge", "label": "Track 05 — Challenge"}),
    "wide-challenge": MappingProxyType({"id": "wide-challenge", "label": "Track 06 — Challenge Wide"}),
    "circle": MappingProxyType({"id": "circle", "label": "Track 07 — Circle"}),
    "wide-circle": MappingProxyType({"id": "wide-circle", "label": "Track 08 — Circle Wide"}),
    "oval": MappingProxyType({"id": "oval", "label": "Track 09 — Oval"}),
    "elliptical": MappingProxyType({"id": "elliptical", "label": "Track 10 — Oval Wide"}),
    "infinity": MappingProxyType({"id": "infinity", "label": "Track 11 — Infinity"}),
    "wide-infinity": MappingProxyType({"id": "wide-infinity", "label": "Track 12 — Infinity Wide"}),
})
_EXPERIMENTS = MappingProxyType({"led-status-v1": "led", "autonomous-car-v1": "autonomous-car"})
# EXPERIMENT_COMPLETE is reserved for a future verified vehicle completion
# integration. Current model actions never emit it.
_LED_PHASES = MappingProxyType({"READY": "LED_READY", "RUNNING": "LED_RUNNING",
                               "REPORTED_COMPLETE": "LED_COMPLETE"})
_MAX_TIMESTAMP = 253402300799


def catalog():
    """Return copies of approved identifiers and labels, never paths or content."""
    return [dict(track) for track in TRACKS.values()]


class LabDisplay:
    def __init__(self):
        self.clock = time.time
        self._lock = threading.RLock()
        self._clear("SETUP_REQUIRED")

    @staticmethod
    def catalog():
        return catalog()

    def _clear(self, mode):
        self._mode = mode
        self._experiment = None
        self._track = None
        self._owner = None
        self._expires_at = None
        self._run_id = None
        self._running_deadline = None

    @staticmethod
    def _valid_number(value):
        # These comparisons reject non-finite floats and arbitrarily large ints.
        return type(value) in (int, float) and 0 <= value <= _MAX_TIMESTAMP

    def _now(self):
        try:
            now = self.clock()
        except Exception:
            return None
        return now if self._valid_number(now) else None

    def _expired(self):
        deadlines = (self._expires_at, self._running_deadline)
        if all(deadline is None for deadline in deadlines):
            return False
        now = self._now()
        return now is None or any(deadline is not None and now >= deadline for deadline in deadlines)

    def expired(self):
        with self._lock:
            return self._expired()

    def _snapshot(self):
        if self._expired():
            # A stale presentation is unknown/recovery, never assumed complete.
            return {"mode": "RECOVERY", "experiment": None, "track": None}
        return {"mode": self._mode, "experiment": _EXPERIMENTS.get(self._experiment),
                "track": self._track}

    def snapshot(self):
        with self._lock:
            return self._snapshot()

    @property
    def owner(self):
        """Private raw owner remains available for application recovery handling."""
        with self._lock:
            return self._owner

    @property
    def experiment(self):
        """Return the internal experiment identifier for application checks."""
        with self._lock:
            return None if self._expired() else self._experiment

    def owned_by(self, owner):
        with self._lock:
            return (type(owner) is str and self._owner is not None
                    and self._owner == owner and not self._expired())

    def prepare(self, experiment, owner, expires_at=None):
        if type(experiment) is not str or experiment not in _EXPERIMENTS:
            raise DisplayError("EXPERIMENT_NOT_ALLOWED")
        if (type(owner) is not str or (owner != "instructor"
                and re.fullmatch(r"workstation:[0-9a-f]{64}", owner) is None)):
            raise DisplayError("DISPLAY_OWNER_INVALID")
        with self._lock:
            if expires_at is not None:
                now = self._now()
                if (not self._valid_number(expires_at) or now is None or expires_at <= now):
                    raise DisplayError("DISPLAY_EXPIRY_INVALID")
            self._clear("LED_SETUP" if experiment == "led-status-v1" else "AUTONOMOUS_CAR_SETUP")
            self._experiment = experiment
            self._owner = owner
            self._expires_at = expires_at
            return self._snapshot()

    def select_track(self, track_id):
        if type(track_id) is not str or track_id not in TRACKS:
            raise DisplayError("TRACK_NOT_ALLOWED")
        with self._lock:
            if (self._expired() or self._experiment != "autonomous-car-v1"
                    or self._mode not in ("AUTONOMOUS_CAR_SETUP", "TRACK_ACTIVE")):
                raise DisplayError("DISPLAY_ORDER")
            # TRACK_ACTIVE means an approved image is displayed, not vehicle execution.
            self._mode = "TRACK_ACTIVE"
            self._track = track_id
            return self._snapshot()

    def idle(self):
        with self._lock:
            self._clear("IDLE")
            return self._snapshot()

    def select_experiment(self):
        with self._lock:
            self._clear("SELECT_EXPERIMENT")
            return self._snapshot()

    def recovery(self):
        with self._lock:
            self._clear("RECOVERY")
            return self._snapshot()

    @staticmethod
    def _valid_run(rid):
        return type(rid) is str and re.fullmatch(r"[0-9a-f]{32}", rid) is not None

    def bind_led_run(self, rid):
        if not self._valid_run(rid):
            raise DisplayError("DISPLAY_RUN_INVALID")
        with self._lock:
            if (self._expired() or self._experiment != "led-status-v1"
                    or self._mode not in ("LED_SETUP", "LED_READY", "LED_COMPLETE")):
                raise DisplayError("DISPLAY_ORDER")
            self._run_id = rid
            self._mode = "LED_READY"
            self._track = None
            self._running_deadline = None
            return self._snapshot()

    def owns_run(self, rid):
        with self._lock:
            return (self._valid_run(rid) and self._run_id is not None
                    and self._run_id == rid and not self._expired())

    def led_phase(self, rid, phase):
        if type(phase) is not str or phase not in _LED_PHASES:
            raise DisplayError("DISPLAY_PHASE_INVALID")
        with self._lock:
            if (not self._valid_run(rid) or self._run_id != rid or self._expired()
                    or self._experiment != "led-status-v1"):
                return False
            if phase == "RUNNING":
                now = self._now()
                if now is None:
                    return False
                self._running_deadline = now + RUNNING_TIMEOUT_SECONDS
            else:
                self._running_deadline = None
            self._mode = _LED_PHASES[phase]
            return True
