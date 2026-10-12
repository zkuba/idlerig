"""Miner against the fake XMRig process (tests/fake_xmrig.py)."""

import sys

import pytest

from conftest import FAKE_XMRIG
from idlerig.xmrig import Miner, PoolIdentity, summary_thread_count, with_identity, with_threads

USER = PoolIdentity("pool.example:3333", "4" + "B" * 94, "pc")
DEV = PoolIdentity("dev.example:3333", "8" + "C" * 94, "idlerig-test", tls=False)


@pytest.fixture
def miner(port, tmp_path):
    m = Miner(FAKE_XMRIG, USER, threads=2, api_port=port, log_dir=tmp_path,
              command_prefix=[sys.executable])
    m.VERIFY_TIMEOUT = 3.0
    yield m
    m.stop()


def test_with_threads_updates_star_and_aliases_other_profiles():
    cfg = {"cpu": {"enabled": True, "*": {"intensity": 2, "threads": 1, "affinity": 5}, "rx": [0, 1, 2], "cn/0": False}}
    out = with_threads(cfg, 6)
    assert out["cpu"]["*"] == {"intensity": 2, "threads": 6, "affinity": 5}
    assert out["cpu"]["rx"] == "*"
    assert out["cpu"]["cn/0"] is False and out["cpu"]["enabled"] is True
    assert cfg["cpu"]["*"]["threads"] == 1  # input untouched


def test_with_identity_keeps_one_pool():
    cfg = {"pools": [{"url": "a", "user": "x", "pass": "y", "keepalive": True}, {"url": "b"}]}
    out = with_identity(cfg, DEV)
    assert out["pools"] == [{"url": DEV.url, "user": DEV.wallet, "pass": DEV.worker, "tls": False, "keepalive": True}]
    assert with_identity({"pools": []}, DEV) is None


def test_command_line(miner):
    cmd = miner.build_command()
    assert "--threads=2" in cmd and "--donate-level=0" in cmd and "--no-huge-pages" not in cmd
    assert any(a.startswith("--http-access-token=") and len(a) > 30 for a in cmd)


def test_start_set_threads_and_stop(miner):
    assert miner.start() and miner.is_running()
    assert summary_thread_count(miner.summary()) == 2
    miner.set_threads(3)
    assert summary_thread_count(miner.summary()) == 3
    assert miner.restarts == 0
    miner.stop()
    assert not miner.is_running()


def test_failed_api_falls_back_to_restart(miner, monkeypatch):
    monkeypatch.setenv("FAKE_XMRIG_NO_PUT", "1")
    miner.start()
    pid = miner.pid
    miner.set_threads(4)
    assert miner.restarts == 1 and miner.pid != pid
    assert "--threads=4" in miner.build_command()
    assert summary_thread_count(miner.summary()) == 4


def test_unconfirmed_thread_change_falls_back_to_restart(miner, monkeypatch):
    monkeypatch.setenv("FAKE_XMRIG_IGNORE_THREADS", "1")
    miner.start()
    miner.set_threads(3)
    assert miner.restarts == 1
    assert summary_thread_count(miner.summary()) == 3


def test_identity_switch_via_api(miner):
    miner.start()
    miner.set_identity(DEV)
    cfg = miner.api.get_config()
    assert cfg["pools"][0]["user"] == DEV.wallet and cfg["pools"][0]["url"] == DEV.url
    assert miner.restarts == 0


def test_zero_threads_pauses_and_resumes(miner):
    miner.start()
    miner.set_threads(0)
    assert miner.paused and miner.summary()["paused"] is True
    miner.set_threads(2)
    assert not miner.paused and miner.summary()["paused"] is False
    assert miner.restarts == 0


def test_watchdog_restarts_crashed_process(miner):
    miner.start()
    miner._proc.kill()
    miner._proc.wait()
    miner.ensure_alive()
    assert miner.is_running() and miner.restarts == 1


def test_crash_loop_backs_off(port, tmp_path):
    m = Miner(tmp_path / "nope.exe", USER, threads=1, api_port=port, log_dir=tmp_path)
    m.start()
    m.ensure_alive()          # 1st failure: immediate retry
    assert m.restarts == 1
    m.ensure_alive()          # 2nd failure: scheduled, not immediate
    assert m.restarts == 1 and m._retry_at > 0


def test_relative_path_survives_cwd_change(port, tmp_path, monkeypatch):
    monkeypatch.chdir(FAKE_XMRIG.parent.parent)
    m = Miner("tests/fake_xmrig.py", USER, threads=1, api_port=port, log_dir=tmp_path,
              command_prefix=[sys.executable])
    try:
        assert m.start() and m.is_running()
    finally:
        m.stop()


def test_command_uses_xmrig_log_file(miner, tmp_path):
    assert f"--log-file={tmp_path.resolve() / 'xmrig.log'}" in miner.build_command()


def test_foreign_xmrig_on_api_port_is_detected(port, tmp_path):
    other = Miner(FAKE_XMRIG, USER, threads=1, api_port=port, log_dir=tmp_path / "a",
                  command_prefix=[sys.executable])
    ours = Miner(FAKE_XMRIG, USER, threads=1, api_port=port, log_dir=tmp_path / "b",
                 command_prefix=[sys.executable])
    ours.READY_TIMEOUT = 5
    try:
        assert other.start()
        assert ours.start() is False  # token rejected by the other instance
        assert not ours.is_running()
    finally:
        ours.stop()
        other.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows-only")
def test_xmrig_dies_with_idlerig(port, tmp_path):
    """Hard-kill a process that owns a Miner; its XMRig must not survive."""
    import subprocess
    import textwrap
    import time

    script = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(FAKE_XMRIG.parent.parent)!r})
        from idlerig.xmrig import Miner, PoolIdentity
        m = Miner({str(FAKE_XMRIG)!r}, PoolIdentity("p:1", "w", "x"), threads=1, api_port={port},
                  log_dir={str(tmp_path)!r}, command_prefix=[sys.executable])
        assert m.start()
        print(m.pid, flush=True)
        time.sleep(60)
    """)
    owner = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    child_pid = int(owner.stdout.readline())
    owner.kill()  # like Task Manager: no clean-up code runs
    owner.wait()
    deadline = time.monotonic() + 5
    alive = True
    while alive and time.monotonic() < deadline:
        alive = subprocess.run(["tasklist", "/FI", f"PID eq {child_pid}", "/NH"],
                               capture_output=True, text=True).stdout.find(str(child_pid)) >= 0
        time.sleep(0.2)
    assert not alive


def test_missing_binary(port, tmp_path):
    m = Miner(tmp_path / "nope.exe", USER, threads=1, api_port=port, log_dir=tmp_path)
    assert m.start() is False
    assert not m.is_running()
