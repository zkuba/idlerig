"""Dev-fee rotator.

IdleRig mines for the user most of the time and periodically switches to the
developer's wallet for a short "dev slice". This keeps the project funded
and, because every installation reports under its own worker name, shows
the developer how many people actually run it.

Schedule (``compute_schedule``), for a dev fee of D percent (1-100):

* dev slice  S = min(15 min, floor(6 h * D / 100)), at least 1 minute
* full cycle   = S * 100 / D   (never longer than 6 hours)
* user slice   = cycle - S; the very first user slice is capped at 15 min,
  so short sessions also contribute

Examples: 2% -> 7 min dev every 5 h 50 min; 1% -> 3 min dev every 5 h.

During a dev slice XMRig always mines on ``DEV_POOL`` (one dashboard for all
installations). A dev slice lasts at least S and until one share has been
accepted, capped at ``SHARE_WAIT_LIMIT``, so slow CPUs still deliver a share.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from idlerig import __version__
from idlerig.xmrig import Miner, PoolIdentity, summary_shares

log = logging.getLogger(__name__)

DEV_WALLET = "87QdreCSsmVC3s9SzctnPuMuEfupAivfdHCstLCKvQQiWtkhfoJFWH1fUMxu3am7Lh9eRHfKPVf5Gi5aKemLqBNpTEEc6oj"
DEV_POOL = "pool.supportxmr.com:3333"
DEV_DASHBOARD = f"https://supportxmr.com/#/dashboard?wallet={DEV_WALLET}"

MIN_PERCENT = 1.0
DEFAULT_PERCENT = 2.0
MAX_DEV_SLICE = 15 * 60
MAX_CYCLE = 6 * 3600
MAX_FIRST_USER_SLICE = 15 * 60
SHARE_WAIT_LIMIT = 20 * 60
SHARE_POLL_INTERVAL = 5.0


@dataclass(frozen=True)
class Schedule:
    percent: float
    dev_seconds: int
    user_seconds: int
    first_user_seconds: int

    @property
    def cycle_seconds(self) -> int:
        return self.dev_seconds + self.user_seconds


def clamp_percent(percent: float) -> float:
    return max(MIN_PERCENT, min(100.0, float(percent)))


def compute_schedule(percent: float) -> Schedule:
    d = clamp_percent(percent)
    dev_minutes = max(1, min(MAX_DEV_SLICE // 60, int(MAX_CYCLE / 60 * d / 100)))
    cycle_seconds = round(dev_minutes * 60 * 100 / d)
    dev_seconds = dev_minutes * 60
    user_seconds = max(0, cycle_seconds - dev_seconds)
    return Schedule(d, dev_seconds, user_seconds, min(user_seconds, MAX_FIRST_USER_SLICE))


def dev_worker_name(user_wallet: str) -> str:
    """Anonymous per-installation worker name, e.g. ``idlerig-0.3.0-1a2b3c4d``."""
    digest = hashlib.sha256(user_wallet.encode("utf-8")).hexdigest()[:8]
    return f"idlerig-{__version__}-{digest}"


class Rotator(threading.Thread):
    def __init__(self, miner: Miner, user: PoolIdentity, percent: float = DEFAULT_PERCENT,
                 clock: Callable[[], float] = time.monotonic):
        super().__init__(name="rotator", daemon=True)
        self.miner = miner
        self.user = user
        self.schedule = compute_schedule(percent)
        self.dev = PoolIdentity(DEV_POOL, DEV_WALLET, dev_worker_name(user.wallet))
        self.clock = clock
        self.owner = "user"
        self.waiting_for_share = False
        self.dev_slices = 0
        self.dev_shares = 0
        self._deadline: Optional[float] = None
        self._stop_event = threading.Event()
        self._wake = threading.Event()

    # -- public ----------------------------------------------------------------------------

    def stop(self) -> None:
        self._stop_event.set()
        self._wake.set()

    def set_user_identity(self, user: PoolIdentity) -> None:
        """Change the user's pool/worker (from the web UI); applied now if mining for the user."""
        self.user = user
        if self.owner == "user":
            self.miner.set_identity(user)

    def status(self) -> Dict[str, Any]:
        remaining = None
        if self._deadline is not None:
            remaining = max(0, int(self._deadline - self.clock()))
        return {
            "owner": self.owner,
            "seconds_to_next": remaining,
            "waiting_for_share": self.waiting_for_share,
            "percent": self.schedule.percent,
            "dev_minutes": self.schedule.dev_seconds / 60,
            "cycle_minutes": self.schedule.cycle_seconds / 60,
            "dev_wallet": DEV_WALLET,
            "dev_pool": DEV_POOL,
            "dev_worker": self.dev.worker,
            "dev_dashboard": DEV_DASHBOARD,
            "dev_slices": self.dev_slices,
            "dev_shares": self.dev_shares,
        }

    # -- loop ------------------------------------------------------------------------------

    def run(self) -> None:
        s = self.schedule
        log.info("Dev fee %.1f%%: %d min on %s (worker %s) every %d min; first after %d min",
                 s.percent, s.dev_seconds // 60, DEV_POOL, self.dev.worker,
                 s.cycle_seconds // 60, s.first_user_seconds // 60)
        user_slice = s.first_user_seconds
        while not self._stop_event.is_set():
            if user_slice > 0:
                self._switch("user")
                if self._sleep(user_slice):
                    break
            user_slice = s.user_seconds
            self._switch("dev")
            if self._dev_slice():
                break
        self._deadline = None
        log.info("Rotator stopped")

    def _switch(self, owner: str) -> None:
        self.owner = owner
        self.miner.set_identity(self.dev if owner == "dev" else self.user)

    def _sleep(self, seconds: float) -> bool:
        """Wait ``seconds``; True if stop was requested."""
        self._deadline = self.clock() + seconds
        while not self._stop_event.is_set():
            left = self._deadline - self.clock()
            if left <= 0:
                return False
            self._wake.wait(min(left, 1.0))
        return True

    def _shares(self) -> Optional[int]:
        s = self.miner.summary()
        return summary_shares(s)["accepted"] if s else None

    def _dev_slice(self) -> bool:
        self.dev_slices += 1
        start = self.clock()
        baseline = self._shares()
        if self._sleep(self.schedule.dev_seconds):
            return True
        # Keep going until at least one share was accepted for the dev wallet.
        current = self._shares()
        self.waiting_for_share = True
        try:
            while not self._stop_event.is_set():
                if current is not None:
                    if baseline is None or current < baseline:  # XMRig restarted: counters reset
                        baseline = 0
                    if current > baseline:
                        self.dev_shares += current - baseline
                        return False
                if self.clock() - start >= SHARE_WAIT_LIMIT:
                    log.info("No dev share within %d min; continuing", SHARE_WAIT_LIMIT // 60)
                    return False
                if self._sleep(SHARE_POLL_INTERVAL):
                    return True
                current = self._shares()
            return True
        finally:
            self.waiting_for_share = False
