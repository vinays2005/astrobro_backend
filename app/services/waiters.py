"""Wake up long-polling clients the moment something changes (a new chat message, a session ending).

One API process serves everything, so an in-memory registry is enough. Subscribe BEFORE checking the database and
wait afterwards: a change that lands in between is then never missed.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager


class Waiters:
    def __init__(self) -> None:
        self._events: dict[str, set[asyncio.Event]] = defaultdict(set)

    def notify(self, key: str) -> None:
        for event in list(self._events.get(key, ())):
            event.set()

    # A change must be visible before anyone is told about it: queue the key on the database session and release it
    # only after the commit succeeds (a rollback drops it), otherwise a woken poller would read the old state.
    @staticmethod
    def notify_after_commit(db, key: str) -> None:
        db.info.setdefault("notify_keys", set()).add(key)

    def flush(self, db) -> None:
        for key in db.info.pop("notify_keys", set()):
            self.notify(key)

    @staticmethod
    def discard(db) -> None:
        db.info.pop("notify_keys", None)

    @asynccontextmanager
    async def subscribe(self, key: str):
        event = asyncio.Event()
        self._events[key].add(event)
        try:
            yield event
        finally:
            self._events[key].discard(event)
            if not self._events[key]:
                del self._events[key]

    @staticmethod
    async def wait(event: asyncio.Event, timeout: float) -> bool:
        try:
            await asyncio.wait_for(event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def watching(self, key: str) -> int:
        return len(self._events.get(key, ()))


waiters = Waiters()
