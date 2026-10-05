"""Small in-memory sliding-window limiter. One worker process serves the API, so memory is enough; a restart simply
forgets the counts. Used for callers who carry no signed-in user (older app versions)."""
from __future__ import annotations

import ipaddress
import time
from collections import defaultdict, deque

from fastapi import Request

_PRIVATE = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
                                              "100.64.0.0/10", "::1/128", "fc00::/7")]


class SlidingWindow:
    def __init__(self, clock=time.monotonic):
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._clock = clock

    def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        """Record one hit for `key` and say whether it is within `limit` hits per window."""
        now = self._clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        if len(self._hits) > 20000:                       # keep memory bounded
            for k in [k for k, v in self._hits.items() if not v][:5000]:
                del self._hits[k]
        return True


def client_ip(request: Request) -> str:
    """The caller's address. Behind Railway's proxies the socket peer is the proxy, so use the right-most public
    entry of X-Forwarded-For (the part the proxy added, not anything the caller typed in front of it)."""
    for part in reversed([p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]):
        try:
            if not any(ipaddress.ip_address(part) in net for net in _PRIVATE):
                return part
        except ValueError:
            continue
    return request.client.host if request.client else "unknown"


limiter = SlidingWindow()
