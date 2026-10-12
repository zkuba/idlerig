from idlerig.governor import Governor
from idlerig.threads import ThreadSpec


class FakeActivity:
    def __init__(self):
        self.idle = 0.0
        self.locked = False

    def idle_seconds(self):
        return self.idle

    def is_locked(self):
        return self.locked


class FakeMiner:
    def __init__(self):
        self.calls = []

    def set_threads(self, n):
        self.calls.append(n)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make():
    act, miner, clock = FakeActivity(), FakeMiner(), Clock()
    g = Governor(miner, ThreadSpec.parse("1,2,4"), idle_after=120, away_after=900, debounce=10,
                 activity=act, clock=clock)
    return g, act, miner, clock


def test_first_state_is_applied_immediately():
    g, act, miner, clock = make()
    g.tick()
    assert g.state == "active" and miner.calls == [1]


def test_lower_activity_is_debounced():
    g, act, miner, clock = make()
    g.tick()
    act.idle = 130
    g.tick()
    clock.t += 5
    g.tick()
    assert g.state == "active"
    clock.t += 5
    g.tick()
    assert g.state == "idle" and miner.calls == [1, 2]


def test_lock_means_away():
    g, act, miner, clock = make()
    g.tick()
    act.locked = True
    g.tick()
    clock.t += 10
    g.tick()
    assert g.state == "away" and miner.calls[-1] == 4


def test_long_idle_means_away():
    g, act, miner, clock = make()
    act.idle = 1000
    g.tick()
    assert g.state == "away"


def test_return_to_active_is_immediate():
    g, act, miner, clock = make()
    act.locked = True
    g.tick()
    assert g.state == "away"
    act.locked = False
    act.idle = 0
    g.tick()
    assert g.state == "active" and miner.calls == [4, 1]


def test_flapping_candidate_restarts_debounce():
    g, act, miner, clock = make()
    g.tick()
    act.idle = 130
    g.tick()
    clock.t += 8
    act.idle = 1000  # now a different lower state
    g.tick()
    clock.t += 8
    g.tick()
    assert g.state == "active"
    clock.t += 2
    g.tick()
    assert g.state == "away"


def test_activity_errors_fall_back_to_active():
    g, act, miner, clock = make()

    def boom():
        raise OSError("nope")

    act.idle_seconds = boom
    g.tick()
    assert g.state == "active"
