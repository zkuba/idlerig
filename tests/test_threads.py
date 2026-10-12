import pytest

from idlerig.threads import ThreadSpec


def test_three_absolute_values():
    s = ThreadSpec.parse("1,2,4")
    assert [s.resolve(st, cpus=8) for st in ("active", "idle", "away")] == [1, 2, 4]


def test_percentages_round_and_keep_at_least_one_thread():
    s = ThreadSpec.parse("10%,50%,100%")
    assert [s.resolve(st, cpus=4) for st in ("active", "idle", "away")] == [1, 2, 4]


def test_percent_rounds_half_up_like_the_web_ui():
    assert ThreadSpec.parse("50%").resolve("active", cpus=5) == 3  # 2.5 -> 3 (Math.round)
    assert ThreadSpec.parse("25%").resolve("active", cpus=6) == 2  # 1.5 -> 2


def test_missing_values_repeat_the_last_one():
    s = ThreadSpec.parse("2")
    assert (s.active, s.idle, s.away) == (2, 2, 2)
    s = ThreadSpec.parse("1,3")
    assert (s.active, s.idle, s.away) == (1, 3, 3)


def test_mixed_and_whitespace():
    s = ThreadSpec.parse(" 1 , 50% ,8 ")
    assert s.resolve("idle", cpus=6) == 3


def test_zero_pauses():
    s = ThreadSpec.parse("0,0%,2")
    assert s.resolve("active", cpus=8) == 0
    assert s.resolve("idle", cpus=8) == 0


def test_absolute_count_is_capped_to_cpus():
    assert ThreadSpec.parse("64").resolve("active", cpus=8) == 8


@pytest.mark.parametrize("bad", ["", "abc", "1,2,3,4", "-1", "150%", "x%", "1-4"])
def test_invalid(bad):
    with pytest.raises(ValueError):
        ThreadSpec.parse(bad)


def test_str_round_trip():
    assert str(ThreadSpec.parse("25%,50%,4")) == "25%,50%,4"
