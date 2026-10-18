"""Transient application request RTT, separate from device reports and evidence."""
import threading
import time


CAR_STATUS_FRESHNESS_SECONDS = 8.0


class StatusRTT:
    """Measure only successful, fully validated status requests.

    A failure invalidates the current value without refreshing the last success
    timestamp. No wall-clock time, device identity, or persistent data is stored.
    """

    def __init__(self, clock=None):
        self._clock = clock or time.monotonic_ns
        self._mutex = threading.Lock()
        self._outcome = None
        self._success_ns = None
        self._duration_ms = None

    def start(self):
        return self._clock()

    def succeeded(self, started_ns):
        finished_ns = self._clock()
        with self._mutex:
            self._duration_ms = max(0, finished_ns - started_ns) / 1_000_000
            self._success_ns = finished_ns
            self._outcome = "SUCCESS"

    def failed(self):
        with self._mutex:
            self._outcome = "FAILED"

    def snapshot(self, available=True):
        with self._mutex:
            age_ns = (
                max(0, self._clock() - self._success_ns)
                if self._success_ns is not None else None
            )
            age_ms = age_ns // 1_000_000 if age_ns is not None else None
            state = self._outcome or "UNAVAILABLE"
            if not available:
                state = "UNAVAILABLE"
            elif state == "SUCCESS" and age_ns > CAR_STATUS_FRESHNESS_SECONDS * 1_000_000_000:
                state = "STALE"
            return {
                "state": state,
                "ms": round(self._duration_ms, 3) if state == "SUCCESS" else None,
                "age_ms": age_ms,
            }
