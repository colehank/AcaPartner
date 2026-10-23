"""Bounded, single-flight observations for UI polling; never execution authority."""
from __future__ import annotations

import copy
import threading
import time
from .store import now


class Observation:
    """One finite local read/probe on demand, at most once per refresh interval.

    Results describe the verification interval, never unchecked current bytes.
    No timer, provider, model or database writer is started here. Explicit fresh
    checks serialize with a background check and then verify again; they never
    promote a cached success to authorization.
    """
    def __init__(self, read, *, interval=60):
        self.read = read
        self.interval = interval
        self.lock = threading.Lock()
        self.work = threading.Lock()
        self.running = False
        self.last = None
        self.error = None
        self.started_at = None
        self.finished_monotonic = None

    def _run(self):
        with self.lock:
            self.started_at = started = now()
        try:
            value = self.read()
        except Exception as error:
            with self.lock:
                self.error = {"type": type(error).__name__, "started_at": started, "finished_at": now()}
            raise
        else:
            record = {"started_at": started, "verified_at": now(), "result": value}
            with self.lock:
                self.last = record
                self.error = None
            return copy.deepcopy(record)
        finally:
            with self.lock:
                self.finished_monotonic = time.monotonic()
                self.running = False

    def _background(self):
        try:
            self._run()
        except Exception:
            pass  # Sanitized, dated failure is available in the observation.
        finally:
            self.work.release()

    def snapshot(self):
        with self.lock:
            due = self.finished_monotonic is None or time.monotonic() - self.finished_monotonic >= self.interval
            if due and not self.running and self.work.acquire(blocking=False):
                self.running = True
                threading.Thread(target=self._background, name="state-verification", daemon=True).start()
            return {"current_state": "unknown", "status": "refreshing" if self.running else "failed" if self.error else "observed" if self.last else "pending",
                    "refresh_interval_seconds": self.interval,
                    "started_at": self.started_at,
                    "last_verification": copy.deepcopy(self.last),
                    "last_error": copy.deepcopy(self.error),
                    "age_seconds": None if self.finished_monotonic is None else max(0, time.monotonic() - self.finished_monotonic),
                    "authorization": False}

    def verify_now(self):
        with self.work:
            with self.lock:
                self.running = True
            return self._run()
