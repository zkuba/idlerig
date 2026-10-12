"""Activity governor: maps user activity to a mining thread count.

States (evaluated once per second):

* ``away``   - workstation locked, or no input for ``away_after`` seconds
* ``idle``   - no input for ``idle_after`` seconds
* ``active`` - otherwise

A new state is applied only after it has been observed continuously for
``debounce`` seconds, so a brief mouse nudge does not cause churn. Going
*back* to ``active`` is applied immediately, because the user should get
their CPU back as soon as they return.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from idlerig.activity import SystemActivity
from idlerig.threads import ThreadSpec
from idlerig.xmrig import Miner

log = logging.getLogger(__name__)


class Governor(threading.Thread):
    TICK = 1.0

    def __init__(self, miner: Miner, spec: ThreadSpec, idle_after: float, away_after: float,
                 debounce: float, activity=None, clock: Callable[[], float] = time.monotonic):
        super().__init__(name="governor", daemon=True)
        self.miner = miner
        self.spec = spec
        self.idle_after = float(idle_after)
        self.away_after = max(float(away_after), self.idle_after)
        self.debounce = float(debounce)
        self.activity = activity or SystemActivity()
        self.clock = clock
        self.state: Optional[str] = None
        self.idle_seconds = 0.0
        self.locked = False
        self._candidate: Optional[str] = None
        self._candidate_since = 0.0
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def observe(self) -> str:
        try:
            self.idle_seconds = self.activity.idle_seconds()
            self.locked = self.activity.is_locked()
        except OSError as e:
            log.debug("Activity detection failed: %s", e)
            return "active"
        if self.locked or self.idle_seconds >= self.away_after:
            return "away"
        if self.idle_seconds >= self.idle_after:
            return "idle"
        return "active"

    def tick(self) -> None:
        """One evaluation step (public for tests)."""
        observed = self.observe()
        now = self.clock()
        if observed == self.state:
            self._candidate = None
            return
        if observed != self._candidate:
            self._candidate, self._candidate_since = observed, now
        immediate = self.state is None or observed == "active"
        if immediate or now - self._candidate_since >= self.debounce:
            self._apply(observed)

    def _apply(self, state: str) -> None:
        threads = self.spec.resolve(state)
        log.info("Activity %s -> %s (idle %.0fs, locked=%s): %s", self.state, state,
                 self.idle_seconds, self.locked, f"{threads} threads" if threads else "paused")
        self.state = state
        self._candidate = None
        self.miner.set_threads(threads)

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
                self.miner.ensure_alive()
            except Exception:
                log.exception("Governor tick failed")
            self._stop_event.wait(self.TICK)
