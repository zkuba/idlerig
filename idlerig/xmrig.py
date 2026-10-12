"""XMRig process management and HTTP API client.

``Miner`` owns the XMRig child process and is the single place that changes
what XMRig does. Live changes go through XMRig's HTTP API first:

* thread count -> ``PUT /1/config`` with an updated ``cpu["*"]`` profile
* pool/wallet  -> ``PUT /1/config`` with an updated ``pools[0]``
* pause/resume -> ``POST /json_rpc``

If the API call fails (or the change cannot be confirmed), XMRig is restarted
with the new settings on the command line. Restarts always use the current
state, so concurrent callers (rotator, governor, web UI) cannot undo each
other's changes.
"""

from __future__ import annotations

import json
import logging
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PoolIdentity:
    """Who the shares are mined for: pool URL, wallet and worker name."""

    url: str
    wallet: str
    worker: str
    tls: bool = False

    def masked(self) -> str:
        w = self.wallet
        short = f"{w[:6]}...{w[-4:]}" if len(w) > 14 else w
        return f"{self.url} wallet={short} worker={self.worker}"


class XMRigApi:
    """Minimal client for the XMRig HTTP API (bound to 127.0.0.1)."""

    def __init__(self, port: int, token: str, host: str = "127.0.0.1", timeout: float = 3.0):
        self.base = f"http://{host}:{port}"
        self.token = token
        self.timeout = timeout
        self.last_status: Optional[int] = None  # HTTP status of the last failed request

    def _request(self, method: str, path: str, body: Any = None) -> Optional[Any]:
        """Return parsed JSON ({} for an empty 2xx body) or None on any failure."""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        self.last_status = None
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            self.last_status = e.code
            log.debug("XMRig API %s %s failed: HTTP %s", method, path, e.code)
            return None
        except (urllib.error.URLError, OSError, ValueError) as e:
            log.debug("XMRig API %s %s failed: %s", method, path, e)
            return None
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            log.debug("XMRig API %s %s returned non-JSON body", method, path)
            return None

    def summary(self) -> Optional[Dict[str, Any]]:
        r = self._request("GET", "/1/summary")
        return r if isinstance(r, dict) and r else None

    def get_config(self) -> Optional[Dict[str, Any]]:
        r = self._request("GET", "/1/config")
        return r if isinstance(r, dict) and r else None

    def put_config(self, config: Dict[str, Any]) -> bool:
        return self._request("PUT", "/1/config", config) is not None

    def rpc(self, method: str) -> bool:
        r = self._request("POST", "/json_rpc", {"jsonrpc": "2.0", "id": 1, "method": method})
        return isinstance(r, dict) and "error" not in r


# ----------------------------------------------------------------------------- summary helpers


def summary_hashrate(summary: Optional[Dict[str, Any]]) -> Optional[float]:
    """Most recent non-null total hashrate (10s, then 60s, then 15m average)."""
    try:
        for v in summary["hashrate"]["total"]:
            if isinstance(v, (int, float)):
                return float(v)
    except (KeyError, TypeError):
        pass
    return None


def summary_thread_count(summary: Optional[Dict[str, Any]]) -> Optional[int]:
    try:
        threads = summary["hashrate"]["threads"]
    except (KeyError, TypeError):
        return None
    return len(threads) if isinstance(threads, list) else None


def summary_shares(summary: Optional[Dict[str, Any]]) -> Dict[str, int]:
    res = (summary or {}).get("results") or {}
    good = int(res.get("shares_good") or 0)
    total = int(res.get("shares_total") or 0)
    return {"accepted": good, "rejected": max(0, total - good), "total": total}


def summary_paused(summary: Optional[Dict[str, Any]]) -> Optional[bool]:
    v = (summary or {}).get("paused")
    return v if isinstance(v, bool) else None


# ----------------------------------------------------------------------------- config edits


def with_threads(config: Dict[str, Any], threads: int) -> Dict[str, Any]:
    """Return a copy of an XMRig config that runs ``threads`` CPU threads.

    ``--threads=N`` makes XMRig create ``cpu["*"] = {intensity, threads, affinity}``.
    We update that profile and point every other CPU profile (lists/objects
    such as ``"rx"`` generated by XMRig's autoconfig) at ``"*"`` so it is not
    shadowed by an algorithm-specific profile.
    """
    cfg = json.loads(json.dumps(config))
    cpu = cfg.setdefault("cpu", {})
    star = cpu.get("*") if isinstance(cpu.get("*"), dict) else {}
    cpu["*"] = {
        "intensity": star.get("intensity", 1),
        "threads": int(threads),
        "affinity": star.get("affinity", -1),
    }
    for key, value in list(cpu.items()):
        if key != "*" and isinstance(value, (list, dict)):
            cpu[key] = "*"
    return cfg


def with_identity(config: Dict[str, Any], identity: PoolIdentity) -> Optional[Dict[str, Any]]:
    cfg = json.loads(json.dumps(config))
    pools = cfg.get("pools")
    if not isinstance(pools, list) or not pools or not isinstance(pools[0], dict):
        return None
    pools[0].update({"url": identity.url, "user": identity.wallet, "pass": identity.worker,
                     "tls": identity.tls})
    # Keep a single pool so XMRig never fails over to a stale wallet.
    cfg["pools"] = pools[:1]
    return cfg


# ----------------------------------------------------------------------------- process


class _KillOnCloseJob:
    """Windows job object that terminates its processes when IdleRig exits.

    The job handle is only closed when IdleRig's process ends - normally, by a
    crash, or by Task Manager - so XMRig can never keep mining as an orphan.
    """

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", ctypes.c_uint64 * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._k32 = k32
        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
        info = ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")

    def assign(self, proc: subprocess.Popen) -> bool:
        return bool(self._k32.AssignProcessToJobObject(self.handle, int(proc._handle)))


_job: Optional[_KillOnCloseJob] = None


def _kill_with_us(proc: subprocess.Popen) -> None:
    """Make ``proc`` die together with IdleRig (Windows only; best effort)."""
    global _job
    if sys.platform != "win32":
        return
    try:
        if _job is None:
            _job = _KillOnCloseJob()
        if not _job.assign(proc):
            log.warning("Could not tie XMRig to IdleRig's lifetime; it may outlive a crash")
    except OSError as e:
        log.warning("Job object unavailable (%s); XMRig may outlive a crash", e)


class Miner:
    """Owns the XMRig process and its live settings."""

    READY_TIMEOUT = 15.0
    VERIFY_TIMEOUT = 15.0
    STABLE_RUN = 60.0        # a run this long resets the crash back-off
    MAX_BACKOFF = 300.0

    def __init__(
        self,
        xmrig_path: str,
        identity: PoolIdentity,
        threads: int,
        api_port: int,
        log_dir: Path,
        huge_pages: bool = True,
        extra_args: Optional[List[str]] = None,
        api_token: Optional[str] = None,
        command_prefix: Optional[List[str]] = None,
    ):
        # Absolute, because XMRig is started with its own directory as cwd.
        self.xmrig_path = str(Path(xmrig_path).resolve())
        self.identity = identity
        self.threads = max(0, int(threads))
        self.api_port = int(api_port)
        self.log_dir = Path(log_dir).resolve()
        self.huge_pages = huge_pages
        self.extra_args = list(extra_args or [])
        # Random per run: XMRig runs with --http-no-restricted, so nothing else
        # on this machine should be able to reconfigure it.
        self.api = XMRigApi(api_port, api_token or secrets.token_urlsafe(24))
        # Lets tests run a Python fake instead of xmrig.exe.
        self.command_prefix = list(command_prefix or [])

        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._log_files: List[Any] = []
        self.wanted_running = False
        self.paused = False
        self.started_at: Optional[float] = None
        self.restarts = 0
        self.crashes = 0
        self._retry_at = 0.0
        self._spawned_at = 0.0
        self.on_change: Optional[Callable[[], None]] = None

    # -- state -----------------------------------------------------------------------------

    @property
    def pid(self) -> Optional[int]:
        p = self._proc
        return p.pid if p and p.poll() is None else None

    def is_running(self) -> bool:
        p = self._proc
        return p is not None and p.poll() is None

    def build_command(self) -> List[str]:
        ident = self.identity
        cmd = self.command_prefix + [
            self.xmrig_path,
            "--url", ident.url,
            "--user", ident.wallet,
            "--pass", ident.worker,
            "--donate-level=0",
            "--no-color",
            "--http-host=127.0.0.1",
            f"--http-port={self.api_port}",
            f"--http-access-token={self.api.token}",
            "--http-no-restricted",
            # XMRig does not write to a redirected stdout on Windows; use its own log file.
            f"--log-file={self.log_dir / 'xmrig.log'}",
        ]
        if ident.tls:
            cmd.append("--tls")
        # XMRig rejects --threads=0; a paused miner keeps 1 thread configured.
        cmd.append(f"--threads={max(1, self.threads)}")
        if not self.huge_pages:
            cmd.append("--no-huge-pages")
        return cmd + self.extra_args

    def _notify(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                log.exception("on_change callback failed")

    # -- lifecycle -------------------------------------------------------------------------

    def start(self, source: Optional[str] = None) -> bool:
        with self._lock:
            if source:
                log.info("Start requested from the %s", source)
            self.wanted_running = True
            if self.is_running():
                return True
            ok = self._spawn()
            self._notify()
            return ok

    def stop(self, source: Optional[str] = None) -> None:
        with self._lock:
            if source:
                log.info("Stop requested from the %s", source)
            self.wanted_running = False
            self._kill()
            self._notify()

    def restart(self, source: Optional[str] = None) -> bool:
        with self._lock:
            if source:
                log.info("Restart requested from the %s", source)
            log.info("Restarting XMRig (threads=%d, %s)", self.threads, self.identity.masked())
            self._kill()
            self.wanted_running = True
            self.restarts += 1
            ok = self._spawn()
            self._notify()
            return ok

    def ensure_alive(self) -> None:
        """Watchdog: restart XMRig if it exited while it should be running.

        Repeated crashes are retried with exponential back-off (5 s ... 5 min).
        """
        with self._lock:
            if not self.wanted_running or self.paused or self.is_running():
                return
            now = time.monotonic()
            if self._retry_at == 0.0:
                code = self._proc.returncode if self._proc else None
                ran = now - self._spawned_at if self._proc else 0.0
                self.crashes = 0 if ran >= self.STABLE_RUN else self.crashes + 1
                delay = 0.0 if self.crashes <= 1 else min(self.MAX_BACKOFF, 5.0 * 2 ** (self.crashes - 2))
                self._retry_at = now + delay
                log.warning("XMRig is not running (exit code %s); restarting%s", code,
                            f" in {delay:.0f}s" if delay else "")
            if now >= self._retry_at:
                self._retry_at = 0.0
                self.restart()

    def _spawn(self) -> bool:
        cmd = self.build_command()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        safe = [("<api-token>" if a.startswith("--http-access-token") else a) for a in cmd]
        log.info("Starting XMRig: %s", " ".join(safe))
        # Catches anything XMRig prints before its log file is open (e.g. bad arguments).
        console = open(self.log_dir / "xmrig_console.log", "ab")
        kwargs: Dict[str, Any] = {"stdout": console, "stderr": subprocess.STDOUT,
                                  "stdin": subprocess.DEVNULL,
                                  "cwd": str(Path(self.xmrig_path).parent)}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            self._proc = subprocess.Popen(cmd, **kwargs)
        except OSError as e:
            console.close()
            self._proc = None
            log.error("Could not start XMRig (%s): %s", self.xmrig_path, e)
            return False
        _kill_with_us(self._proc)
        self._log_files = [console]
        self.started_at = time.time()
        self._spawned_at = time.monotonic()
        self.paused = False
        if not self._wait_ready():
            if self.is_running():
                log.warning("XMRig HTTP API not reachable on port %d after %.0fs; "
                            "live changes will fall back to restarts", self.api_port, self.READY_TIMEOUT)
            return self.is_running()
        log.info("XMRig running (pid %s)", self._proc.pid)
        if self.threads == 0:
            self._pause()
        return True

    def _wait_ready(self) -> bool:
        deadline = time.monotonic() + self.READY_TIMEOUT
        while time.monotonic() < deadline:
            if not self.is_running():
                log.error("XMRig exited during start-up (code %s); see %s",
                          self._proc.returncode if self._proc else "?", self.log_dir / "xmrig_console.log")
                return False
            if self.api.summary() is not None:
                return True
            if self.api.last_status in (401, 403):
                # Our token was rejected: another XMRig already owns the API port and ours
                # could not bind it. Running ours without an API would be uncontrollable.
                log.error("Port %d is used by another XMRig that IdleRig did not start. "
                          "Stop it, or pass --xmrig-http-port with a free port.", self.api_port)
                self._kill()
                return False
            time.sleep(0.3)
        return False

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            log.info("XMRig stopped")
        for f in self._log_files:
            f.close()
        self._log_files = []
        self.started_at = None

    # -- live changes ----------------------------------------------------------------------

    def set_threads(self, threads: int) -> None:
        """Change the thread count; 0 pauses mining."""
        threads = max(0, int(threads))
        with self._lock:
            previous = self.threads
            self.threads = threads
            if threads == 0:
                if self.is_running() and not self.paused:
                    self._pause()
                return
            if self.paused:
                # Resuming may restart XMRig, which already applies self.threads.
                if self._resume():
                    return
            if not self.is_running():
                return  # used on the next start
            if threads != previous and not self._apply_threads(threads):
                log.info("Applying %d threads via API failed; restarting XMRig", threads)
                self.restart()
                return
            self._notify()

    def _apply_threads(self, threads: int) -> bool:
        cfg = self.api.get_config()
        if cfg is None or not self.api.put_config(with_threads(cfg, threads)):
            return False
        # Confirm the change when XMRig reports per-thread hashrates.
        deadline = time.monotonic() + self.VERIFY_TIMEOUT
        count = None
        while time.monotonic() < deadline:
            count = summary_thread_count(self.api.summary())
            if count is None or count == threads:
                log.info("Threads set to %d via API", threads)
                return True
            time.sleep(0.5)
        log.warning("XMRig still reports %s threads after setting %d", count, threads)
        return False

    def _pause(self) -> None:
        if self.api.rpc("pause"):
            self.paused = True
            log.info("Mining paused")
        else:
            log.warning("Pause via API failed; stopping XMRig instead")
            self._kill()
            self.paused = True
        self._notify()

    def _resume(self) -> bool:
        """Resume mining. Returns True if XMRig had to be (re)started to do so."""
        self.paused = False
        if self.is_running() and self.api.rpc("resume"):
            log.info("Mining resumed")
            return False
        if self.wanted_running:
            self.restart()
        return True

    def set_identity(self, identity: PoolIdentity) -> None:
        """Switch pool/wallet/worker (used by the dev-fee rotator)."""
        with self._lock:
            if identity == self.identity:
                return
            self.identity = identity
            if not self.is_running():
                return  # used on the next start
            cfg = self.api.get_config()
            new_cfg = with_identity(cfg, identity) if cfg else None
            if new_cfg is not None and self.api.put_config(new_cfg):
                log.info("Switched to %s via API", identity.masked())
            else:
                log.info("Switching pool via API failed; restarting XMRig")
                self.restart()
            self._notify()

    def summary(self) -> Optional[Dict[str, Any]]:
        return self.api.summary() if self.is_running() else None
