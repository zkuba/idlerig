"""Local web UI and JSON API (standard library only).

The server binds to 127.0.0.1. Every ``/api/*`` request needs the access
token, sent as ``Authorization: Bearer <token>``, ``X-Auth-Token: <token>``
or ``?token=<token>`` (the query form exists for file downloads). Requests
whose ``Host`` header is not a loopback name are rejected to block DNS
rebinding.

Endpoints:

* ``GET  /``                     the UI (token is passed in the URL fragment)
* ``GET  /api/status``           miner, activity and dev-fee state
* ``GET  /api/logs?since=N``     new lines of idlerig.log after byte offset N
* ``GET  /api/download/app``     idlerig.log
* ``GET  /api/download/xmrig``   xmrig.log
* ``POST /api/control``          {"action": "start" | "stop" | "restart"}
                                 {"action": "set_threads", "threads": "1,50%,100%"}
                                 {"action": "set_pool", "pool": "...", "worker": "..."}
"""

from __future__ import annotations

import hmac
import json
import logging
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from idlerig import __version__
from idlerig.governor import Governor
from idlerig.rotator import Rotator
from idlerig.threads import ThreadSpec, cpu_count
from idlerig.xmrig import Miner, summary_hashrate, summary_shares

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"
LOG_TAIL_BYTES = 64 * 1024
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


class Services:
    """What the web layer needs to see and control."""

    def __init__(self, miner: Miner, governor: Governor, rotator: Rotator, log_dir: Path):
        self.miner = miner
        self.governor = governor
        self.rotator = rotator
        self.log_dir = Path(log_dir)

    def status(self) -> Dict[str, Any]:
        m, g = self.miner, self.governor
        summary = m.summary()
        ident = m.identity
        user = self.rotator.user
        return {
            "version": __version__,
            "miner": {
                "running": m.is_running(),
                "paused": m.paused,
                "pid": m.pid,
                "threads": m.threads,
                "uptime": int(time.time() - m.started_at) if m.started_at else None,
                "restarts": m.restarts,
                "hashrate": summary_hashrate(summary),
                "shares": summary_shares(summary),
                "pool": ident.url,
                "wallet": ident.wallet,
                "worker": ident.worker,
            },
            "activity": {
                "state": g.state,
                "idle_seconds": round(g.idle_seconds),
                "locked": g.locked,
                "threads_spec": str(g.spec),
                "idle_after": g.idle_after,
                "away_after": g.away_after,
                "debounce": g.debounce,
                "cpu_count": cpu_count(),
            },
            "user": {"pool": user.url, "wallet": user.wallet, "worker": user.worker},
            "dev_fee": self.rotator.status(),
        }

    def control(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        action = payload.get("action")
        if action == "start":
            return 200, {"ok": self.miner.start(source="web UI")}
        if action == "stop":
            self.miner.stop(source="web UI")
            return 200, {"ok": True}
        if action == "restart":
            return 200, {"ok": self.miner.restart(source="web UI")}
        if action == "set_threads":
            try:
                spec = ThreadSpec.parse(str(payload.get("threads", "")))
            except ValueError as e:
                return 400, {"ok": False, "error": str(e)}
            self.governor.spec = spec
            if self.governor.state:
                self.miner.set_threads(spec.resolve(self.governor.state))
            log.info("Thread spec changed to %s from the web UI", spec)
            return 200, {"ok": True, "threads": str(spec)}
        if action == "set_pool":
            pool = str(payload.get("pool") or "").strip()
            worker = str(payload.get("worker") or "").strip()
            if not pool and not worker:
                return 400, {"ok": False, "error": "nothing to change"}
            user = self.rotator.user
            new = replace(user, url=pool or user.url, worker=worker or user.worker)
            log.info("User pool changed from the web UI: %s", new.masked())
            self.rotator.set_user_identity(new)
            return 200, {"ok": True}
        return 400, {"ok": False, "error": f"unknown action: {action!r}"}

    def read_log(self, since: int) -> Dict[str, Any]:
        path = self.log_dir / "idlerig.log"
        if not path.exists():
            return {"offset": 0, "lines": []}
        size = path.stat().st_size
        tail = since < 0 or since > size  # first request, or the log was rotated
        if tail:
            since = max(0, size - LOG_TAIL_BYTES)
        with open(path, "rb") as f:
            f.seek(since)
            data = f.read(size - since)
        if tail and since > 0:  # drop the partial first line of a tail
            cut = data.find(b"\n") + 1
            data, since = data[cut:], since + cut
        # Only hand out complete lines; the remainder is picked up next time.
        end = data.rfind(b"\n") + 1
        lines = data[:end].decode("utf-8", errors="replace").splitlines()
        return {"offset": since + end, "lines": lines}


class _Handler(BaseHTTPRequestHandler):
    server: "WebServer"
    server_version = f"IdleRig/{__version__}"

    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("HTTP %s - %s", self.address_string(), fmt % args)

    # -- helpers ---------------------------------------------------------------------------

    def _send(self, code: int, body: bytes, content_type: str, extra: Optional[Dict[str, str]] = None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                   "Referrer-Policy": "no-referrer", **(extra or {})}
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: Any) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        return name in LOOPBACK_HOSTS

    def _token_ok(self, query: Dict[str, list]) -> bool:
        token = self.headers.get("X-Auth-Token")
        auth = self.headers.get("Authorization") or ""
        if not token and auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        if not token:
            token = (query.get("token") or [""])[0]
        return bool(token) and hmac.compare_digest(token, self.server.token)

    def _guard(self, query: Dict[str, list]) -> bool:
        if not self._host_ok():
            self._json(403, {"ok": False, "error": "forbidden host"})
            return False
        if not self._token_ok(query):
            self._json(401, {"ok": False, "error": "unauthorized"})
            return False
        return True

    # -- routes ----------------------------------------------------------------------------

    def do_GET(self) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query)
        services = self.server.services
        if url.path in ("/", "/index.html"):
            if not self._host_ok():
                return self._json(403, {"ok": False, "error": "forbidden host"})
            body = (WEB_DIR / "index.html").read_bytes()
            return self._send(200, body, "text/html; charset=utf-8",
                              {"Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                          "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'"})
        if url.path == "/favicon.svg":
            return self._send(200, (WEB_DIR / "favicon.svg").read_bytes(), "image/svg+xml",
                              {"Cache-Control": "max-age=86400"})
        if not url.path.startswith("/api/"):
            return self._json(404, {"ok": False, "error": "not found"})
        if not self._guard(query):
            return
        if url.path == "/api/status":
            return self._json(200, services.status())
        if url.path == "/api/logs":
            try:
                since = int((query.get("since") or ["-1"])[0])
            except ValueError:
                since = -1
            return self._json(200, services.read_log(since))
        if url.path in ("/api/download/app", "/api/download/xmrig"):
            name = "idlerig.log" if url.path.endswith("/app") else "xmrig.log"
            path = services.log_dir / name
            if not path.exists():
                return self._json(404, {"ok": False, "error": f"{name} not found"})
            return self._send(200, path.read_bytes(), "text/plain; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="{name}"'})
        return self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        url = urlparse(self.path)
        if not self._guard(parse_qs(url.query)):
            return
        if url.path != "/api/control":
            return self._json(404, {"ok": False, "error": "not found"})
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 64 * 1024)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("body must be a JSON object")
        except ValueError as e:
            return self._json(400, {"ok": False, "error": f"invalid JSON: {e}"})
        try:
            code, body = self.server.services.control(payload)
        except Exception as e:
            log.exception("Control action failed: %s", payload.get("action"))
            code, body = 500, {"ok": False, "error": str(e)}
        self._json(code, body)


class WebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, services: Services, port: int, token: str):
        super().__init__(("127.0.0.1", port), _Handler)
        self.services = services
        self.token = token
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/"

    def start(self) -> None:
        self._thread = threading.Thread(target=self.serve_forever, name="web", daemon=True)
        self._thread.start()
        log.info("Web UI on %s", self.url)

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
