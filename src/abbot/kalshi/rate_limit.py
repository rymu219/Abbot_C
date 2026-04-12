"""Rate limiter for Kalshi API calls.

Basic tier: 20 reads/sec, 10 writes/sec.
Uses a simple token bucket approach with sleep-based throttling.
"""

import time
import threading


class RateLimiter:
    """Token bucket rate limiter. Thread-safe."""

    def __init__(self, calls_per_second: float = 18.0):
        """Initialize with calls_per_second (default 18, below the 20/s limit)."""
        self._interval = 1.0 / calls_per_second
        self._last_call = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Block until the next call is allowed."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._interval:
                time.sleep(self._interval - elapsed)
            self._last_call = time.monotonic()
