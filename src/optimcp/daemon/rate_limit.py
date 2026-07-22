"""Simple per-token rate limiting for high-volume check/ingest endpoints."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from threading import Lock
from typing import DefaultDict, List


class RateLimitExceeded(Exception):
    """Raised when a token exceeds its request budget."""

    def __init__(self, limit_per_minute: int) -> None:
        self.limit_per_minute = limit_per_minute
        super().__init__(f"rate limit exceeded ({limit_per_minute}/minute)")


class TokenRateLimiter:
    """Fixed-window-ish limiter: max N requests per token per rolling 60s."""

    def __init__(self, limit_per_minute: int) -> None:
        self.limit_per_minute = max(1, int(limit_per_minute))
        self._events: DefaultDict[str, List[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, token_key: str) -> None:
        """Record one request or raise :class:`RateLimitExceeded`."""
        now = time.monotonic()
        cutoff = now - 60.0
        key = token_key or "anonymous"
        with self._lock:
            window = [t for t in self._events[key] if t > cutoff]
            if len(window) >= self.limit_per_minute:
                self._events[key] = window
                raise RateLimitExceeded(self.limit_per_minute)
            window.append(now)
            self._events[key] = window


def default_limit_per_minute() -> int:
    raw = os.getenv("OPTIMCP_RATE_LIMIT_PER_MINUTE", "120")
    try:
        return max(1, int(raw))
    except ValueError:
        return 120
