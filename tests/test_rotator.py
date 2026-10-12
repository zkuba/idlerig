import re
import threading
import time

import pytest

from idlerig import rotator as rot
from idlerig.rotator import DEV_POOL, DEV_WALLET, Rotator, Schedule, compute_schedule, dev_worker_name
from idlerig.xmrig import PoolIdentity


@pytest.mark.parametrize("pct, dev_min, user_min", [
    (1, 3, 297),
    (2, 7, 343),
    (5, 15, 285),
    (10, 15, 135),
    (50, 15, 15),
    (100, 15, 0),
])
def test_schedule(pct, dev_min, user_min):
    s = compute_schedule(pct)
    assert s.dev_seconds == dev_min * 60
    assert s.user_seconds == user_min * 60
    assert s.cycle_seconds <= 6 * 3600
    assert s.first_user_seconds == min(user_min * 60, 15 * 60)


def test_percent_is_clamped_to_minimum():
    assert compute_schedule(0).percent == 1.0
    assert compute_schedule(0.2) == compute_schedule(1)
    assert compute_schedule(500).percent == 100.0


def test_dev_worker_name_is_anonymous_and_stable():
    name = dev_worker_name("4" + "A" * 94)
    assert re.fullmatch(r"idlerig-\d+\.\d+\.\d+-[0-9a-f]{8}", name)
    assert name == dev_worker_name("4" + "A" * 94)
    assert "AAAA" not in name


class FakeMiner:
    """Records identity switches; accepts a share every `share_every` summary calls on the dev pool."""

    def __init__(self, share_every=1):
        self.identity = None
        self.switches = []
        self.shares = 0
        self.share_every = share_every
        self._calls = 0
        self.lock = threading.Lock()

    def set_identity(self, ident):
        with self.lock:
            self.identity = ident
            self.switches.append(ident.wallet)

    def summary(self):
        with self.lock:
            self._calls += 1
            if self.identity and self.identity.wallet == DEV_WALLET and self._calls % self.share_every == 0:
                self.shares += 1
            return {"results": {"shares_good": self.shares, "shares_total": self.shares}}


USER = PoolIdentity("pool.example:3333", "4" + "B" * 94, "pc")


def run_rotator(miner, schedule, seconds, monkeypatch):
    monkeypatch.setattr(rot, "SHARE_POLL_INTERVAL", 0.05)
    r = Rotator(miner, USER, 2)
    r.schedule = schedule
    r.start()
    time.sleep(seconds)
    r.stop()
    r.join(timeout=3)
    assert not r.is_alive()
    return r


def test_rotation_alternates_and_uses_dev_pool(monkeypatch):
    m = FakeMiner()
    r = run_rotator(m, Schedule(2, dev_seconds=0.3, user_seconds=0.3, first_user_seconds=0.1), 1.6, monkeypatch)
    assert m.switches[0] == USER.wallet
    assert DEV_WALLET in m.switches
    assert all(a != b for a, b in zip(m.switches, m.switches[1:]))  # strictly alternating
    assert r.dev.url == DEV_POOL and r.dev.worker.startswith("idlerig-")
    assert r.dev_slices >= 2 and r.dev_shares >= 1


def test_dev_slice_waits_for_a_share(monkeypatch):
    m = FakeMiner(share_every=10**9)  # never produces a share
    monkeypatch.setattr(rot, "SHARE_WAIT_LIMIT", 0.8)
    r = run_rotator(m, Schedule(2, dev_seconds=0.1, user_seconds=5, first_user_seconds=0.05), 0.5, monkeypatch)
    # Dev time (0.1 s) has passed but no share yet: still on the dev wallet.
    assert m.switches == [USER.wallet, DEV_WALLET]
    assert r.dev_shares == 0


def test_status_exposes_dev_wallet():
    r = Rotator(FakeMiner(), USER, 2)
    st = r.status()
    assert st["dev_wallet"] == DEV_WALLET and st["percent"] == 2 and st["owner"] == "user"
    assert DEV_WALLET in st["dev_dashboard"]
