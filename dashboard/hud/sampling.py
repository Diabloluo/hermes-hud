"""Bounded, shared sampling for expensive read-only snapshot diagnostics."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
import time


class PeriodicSample:
    """Synchronous cold read, then reuse for a bounded interval across locales."""
    def __init__(self, interval: float = 30.0):
        self.interval = interval
        self._lock = Lock()
        self._entries = {}

    def read(self, key, collect):
        with self._lock:
            entry = self._entries.get(key)
            now = time.monotonic()
            retry = 2.0 if entry and entry[0].get("error") else self.interval
            if entry is None or now - entry[1] >= retry:
                value = collect()
                entry = (deepcopy(value), time.monotonic(), time.time())
                if len(self._entries) >= 8:
                    self._entries.pop(next(iter(self._entries)))
                self._entries[key] = entry
            value = deepcopy(entry[0])
            value.update(sampled_at=entry[2], sample_age_seconds=max(0, time.monotonic()-entry[1]),
                         refresh_interval_seconds=self.interval,
                         sample_status="unavailable" if value.get("error") else "ready")
            return value


class BackgroundSamples:
    """Cold and expired diagnostics never wait for subprocess/process discovery.

    One in-flight job per key; failures retry at the same low sampling frequency.
    Entry count and worker count are bounded. Samples are detached from callers.
    Refreshing reuses the last observation for at most two sampling intervals;
    a failed result or an observation beyond that age remains unavailable/stale.
    """
    def __init__(self, interval: float = 30.0):
        self.interval = interval
        self._lock = Lock()
        self._entries = {}
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hud-diagnostics")

    @staticmethod
    def _collect(collect):
        try:
            value = collect()
        except Exception:
            value = {"error": "diagnostic_unavailable"}
        return deepcopy(value), time.monotonic(), time.time()

    def read(self, key, collect, pending):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                # Do not evict running jobs and accidentally duplicate discovery.
                if len(self._entries) >= 8:
                    removable = next((k for k, e in self._entries.items()
                                      if e["future"] is None or e["future"].done()), None)
                    if removable is None:
                        return {**deepcopy(pending), "sample_status": "pending", "sampled_at": None,
                                "sample_age_seconds": None, "refresh_interval_seconds": self.interval}
                    self._entries.pop(removable)
                entry = {"sample": None, "future": None}
                self._entries[key] = entry
            future = entry["future"]
            if future is not None and future.done():
                entry["sample"] = future.result()
                entry["future"] = None
            sample = entry["sample"]
            age = max(0, time.monotonic()-sample[1]) if sample else None
            expired = sample is None or age >= self.interval
            if expired and entry["future"] is None:
                entry["future"] = self._pool.submit(self._collect, collect)
            value = deepcopy(sample[0]) if sample else deepcopy(pending)
            # A scheduled refresh is not a service-health failure. Retain the
            # last observation while refreshing, but bound its usable age.
            status = ("pending" if sample is None else
                      "unavailable" if value.get("error") else
                      "stale" if age >= 2 * self.interval else
                      "refreshing" if expired else "ready")
            value.update(sample_status=status, sampled_at=sample[2] if sample else None,
                         sample_age_seconds=age, refresh_interval_seconds=self.interval)
            return value

    def wait_idle(self):
        """Drain captured jobs before an isolated test tears down its mock inputs."""
        with self._lock:
            futures = [e["future"] for e in self._entries.values() if e["future"] is not None]
        for future in futures:
            future.result()
