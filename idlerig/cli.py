"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import re
import secrets
import shutil
import signal
import socket
import sys
import threading
from pathlib import Path
from typing import List, Optional

from idlerig import __app_name__, __version__
from idlerig import tray as tray_mod
from idlerig.governor import Governor
from idlerig.rotator import DEFAULT_PERCENT, DEV_WALLET, MIN_PERCENT, Rotator
from idlerig.threads import ThreadSpec, cpu_count
from idlerig.web import Services, WebServer
from idlerig.xmrig import Miner, PoolIdentity

log = logging.getLogger("idlerig")

DEFAULT_POOL = "pool.supportxmr.com:3333"
DEFAULT_THREADS = "25%,50%,75%"
DEFAULT_HTTP_PORT = 5515
DEFAULT_XMRIG_API_PORT = 18080
PLACEHOLDER_WALLETS = {"", "YOUR_WALLET", "TWOJ_PORTFEL", "<wallet>", "WALLET"}
MONERO_ADDRESS = re.compile(r"^[48][1-9A-HJ-NP-Za-km-z]{94}([1-9A-HJ-NP-Za-km-z]{11})?$")


def app_dir() -> Path:
    """Directory of IdleRig.exe when compiled, otherwise the current directory."""
    if "__compiled__" in globals():
        return Path(sys.argv[0]).resolve().parent
    return Path.cwd()


def show_message(text: str, error: bool) -> None:
    """Message box for the windowless build, where stdout/stderr do not exist."""
    import ctypes
    flags = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
    ctypes.windll.user32.MessageBoxW(None, text.strip(), __app_name__, flags)


def has_console() -> bool:
    """False for the windowless .exe (stdout/stderr then go nowhere).

    Only the compiled build is checked for a console window: a source run with
    piped output (tests, CI) has no console window but a perfectly good stdout.
    """
    if sys.stdout is None:
        return False
    if sys.platform == "win32" and "__compiled__" in globals():
        import ctypes
        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    return True


class Parser(argparse.ArgumentParser):
    """ArgumentParser that falls back to a message box when there is no console."""

    def _print_message(self, message: str, file=None) -> None:
        if not message:
            return
        if sys.platform == "win32" and not has_console():
            show_message(message, error="error:" in message)
            return
        stream = file or sys.stdout
        if stream is not None:
            stream.write(message)

    def error(self, message: str):
        # One message instead of argparse's separate usage + error outputs.
        self.exit(2, f"{self.prog}: error: {message}\n\nRun IdleRig --help for all options.\n")


def build_parser() -> argparse.ArgumentParser:
    p = Parser(
        prog="IdleRig",
        description="Activity-aware controller for XMRig: few threads while you work, "
                    "more when you are away.",
        epilog="Documentation: docs/configuration.md",
    )
    p.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")

    g = p.add_argument_group("mining")
    g.add_argument("-u", "--wallet", required=True, help="your Monero wallet address (required)")
    g.add_argument("-o", "--pool", default=DEFAULT_POOL, help=f"pool host:port (default {DEFAULT_POOL})")
    g.add_argument("-p", "--worker", default=os.environ.get("COMPUTERNAME") or socket.gethostname(),
                   help="worker name shown on the pool (default: computer name)")
    g.add_argument("--tls", action="store_true", help="connect to the pool with TLS")
    g.add_argument("--xmrig-path", default=None,
                   help="path to xmrig.exe (default: next to IdleRig, then PATH)")
    g.add_argument("--xmrig-arg", action="append", default=[], metavar="ARG",
                   help="extra argument passed to XMRig; repeatable, e.g. --xmrig-arg=--cpu-priority=1")
    g.add_argument("--no-huge-pages", action="store_true",
                   help="disable huge pages (slower; use only if XMRig fails to start with them)")
    g.add_argument("--donate-level", type=float, default=DEFAULT_PERCENT, metavar="PERCENT",
                   help=f"dev fee in percent, {MIN_PERCENT:g}-100 (default {DEFAULT_PERCENT:g}); see docs/dev-fee.md")

    g = p.add_argument_group("activity")
    g.add_argument("-t", "--threads", default=DEFAULT_THREADS, metavar="SPEC",
                   help=f'threads for active,idle,away, e.g. "2,4,8" or "25%%,50%%,100%%"; '
                        f'0 pauses mining (default "{DEFAULT_THREADS.replace("%", "%%")}")')
    g.add_argument("--idle-after-min", type=float, default=2.0, metavar="MIN",
                   help="minutes without input before the idle state (default 2)")
    g.add_argument("--away-after-min", "--logout-after-min", dest="away_after_min", type=float,
                   default=10.0, metavar="MIN",
                   help="minutes without input before the away state; a locked screen is "
                        "always away (default 10)")
    g.add_argument("--state-debounce-sec", type=float, default=10.0, metavar="SEC",
                   help="a lower-activity state must hold this long before it is applied (default 10)")

    g = p.add_argument_group("interface")
    g.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT,
                   help=f"web UI port on 127.0.0.1 (default {DEFAULT_HTTP_PORT})")
    g.add_argument("--http-token", default=None,
                   help="web UI/API access token (default: random each run; the tray opens the UI with it)")
    g.add_argument("--no-web", action="store_true", help="do not start the web UI")
    g.add_argument("--no-tray", action="store_true", help="do not show the tray icon")
    g.add_argument("--xmrig-http-port", "--http-port-xmrig", dest="xmrig_http_port", type=int,
                   default=DEFAULT_XMRIG_API_PORT,
                   help=f"internal XMRig API port on 127.0.0.1 (default {DEFAULT_XMRIG_API_PORT})")
    g.add_argument("--log-dir", type=Path, default=None, help="log directory (default: ./logs)")
    g.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    # Accepted for compatibility with ZenMiner 0.2.x; no effect.
    p.add_argument("--tp", type=float, default=None, help=argparse.SUPPRESS)
    p.add_argument("--http-debug", action="store_true", help=argparse.SUPPRESS)
    return p


def setup_logging(log_dir: Path, verbose: bool) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handlers: List[logging.Handler] = [logging.handlers.RotatingFileHandler(
        log_dir / "idlerig.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")]
    if sys.stderr is not None:  # None in the windowless build
        handlers.append(logging.StreamHandler())
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)


def find_xmrig(explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        path = Path(explicit)
        if not path.is_absolute() and not path.exists():
            path = app_dir() / explicit
            if not path.is_file() and shutil.which(explicit):
                path = Path(shutil.which(explicit))
        return path if path.is_file() else None
    for candidate in (app_dir() / "xmrig.exe", app_dir() / "xmrig"):
        if candidate.is_file():
            return candidate
    found = shutil.which("xmrig")
    return Path(found) if found else None


def validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> ThreadSpec:
    if args.wallet.strip() in PLACEHOLDER_WALLETS:
        parser.error("set --wallet to your own Monero address (the example value is a placeholder)")
    try:
        spec = ThreadSpec.parse(args.threads)
    except ValueError as e:
        parser.error(f"--threads: {e}")
    if args.idle_after_min < 0 or args.away_after_min < 0 or args.state_debounce_sec < 0:
        parser.error("timing options must not be negative")
    return spec


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    spec = validate(args, parser)

    log_dir = (args.log_dir or app_dir() / "logs").resolve()
    setup_logging(log_dir, args.verbose or args.http_debug)
    log.info("%s %s starting (logs in %s)", __app_name__, __version__, log_dir)
    if args.tp is not None:
        log.warning("--tp is obsolete and ignored; the dev-fee cycle follows --donate-level")

    if not MONERO_ADDRESS.match(args.wallet.split(".")[0].split("+")[0]):
        log.warning("Wallet does not look like a Monero address; the pool may reject it")
    if args.wallet == DEV_WALLET:
        log.warning("--wallet is the developer's wallet: all mining goes to the developer")

    percent = args.donate_level
    if not MIN_PERCENT <= percent <= 100:
        log.warning("--donate-level %.2f is outside %g-100; clamped", percent, MIN_PERCENT)

    xmrig = find_xmrig(args.xmrig_path)
    if xmrig is None:
        msg = f"XMRig not found ({args.xmrig_path or 'xmrig.exe next to IdleRig or on PATH'})"
        log.error(msg)
        parser.exit(1, f"error: {msg}\n")

    user = PoolIdentity(args.pool, args.wallet, args.worker, tls=args.tls)
    command_prefix = [sys.executable] if xmrig.suffix == ".py" else None  # test fake
    miner = Miner(xmrig, user, threads=1, api_port=args.xmrig_http_port, log_dir=log_dir,
                  huge_pages=not args.no_huge_pages, extra_args=args.xmrig_arg,
                  command_prefix=command_prefix)
    governor = Governor(miner, spec, idle_after=args.idle_after_min * 60,
                        away_after=args.away_after_min * 60, debounce=args.state_debounce_sec)
    rotator = Rotator(miner, user, percent)

    initial = governor.observe()
    miner.threads = spec.resolve(initial)
    log.info("CPU threads available: %d; spec %s -> %s in state %s",
             cpu_count(), spec, miner.threads, initial)
    if not miner.start():
        log.error("XMRig failed to start; see %s", log_dir / "xmrig_console.log")

    rotator.start()
    governor.start()

    stop = threading.Event()
    services = Services(miner, governor, rotator, log_dir)
    web = None
    token = args.http_token or secrets.token_urlsafe(16)
    ui_url = ""
    if not args.no_web:
        try:
            web = WebServer(services, args.http_port, token)
        except OSError as e:
            log.error("Cannot open web UI port %d (%s). Is another instance running?", args.http_port, e)
        else:
            web.start()
            ui_url = f"{web.url}#token={token}"
            if not args.http_token:
                log.info("Web UI access: %s", ui_url)

    tray = None
    if not args.no_tray and ui_url:
        if tray_mod.available():
            tray = tray_mod.Tray(services, ui_url, on_exit=stop.set)
            miner.on_change = tray.refresh
            threading.Thread(target=tray.run, name="tray", daemon=True).start()
        else:
            log.info("Tray icon disabled (install pystray and Pillow to enable it)")

    def on_signal(signum, _frame):
        log.info("Signal %s received", signum)
        stop.set()

    signal.signal(signal.SIGINT, on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, on_signal)
    if hasattr(signal, "SIGBREAK"):  # Ctrl+Break / console close on Windows
        signal.signal(signal.SIGBREAK, on_signal)

    try:
        while not stop.wait(5.0):
            if tray:
                tray.refresh()
    finally:
        log.info("Shutting down")
        rotator.stop()
        governor.stop()
        miner.stop()
        if web:
            web.stop()
        if tray:
            tray.stop()
        log.info("Bye")
    return 0
