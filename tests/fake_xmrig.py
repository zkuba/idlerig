"""A stand-in for xmrig.exe used by tests and smoke runs.

It accepts the command line IdleRig passes to XMRig and serves the parts of
the XMRig HTTP API that IdleRig uses (/1/summary, /1/config, /json_rpc).
One share is "accepted" every FAKE_SHARE_INTERVAL seconds (default 2).

Environment switches for failure tests:
  FAKE_XMRIG_NO_PUT=1      PUT /1/config returns 500
  FAKE_XMRIG_IGNORE_THREADS=1  accept PUT but keep the old thread count
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--url")
    p.add_argument("--user")
    p.add_argument("--pass", dest="password")
    p.add_argument("--threads", type=int, default=1)
    p.add_argument("--http-port", type=int, required=True)
    p.add_argument("--http-access-token", required=True)
    p.add_argument("--tls", action="store_true")
    args, _unknown = p.parse_known_args(argv)
    return args


class State:
    def __init__(self, args):
        self.lock = threading.Lock()
        self.started = time.time()
        self.paused = False
        self.shares = 0
        self.config = {
            "api": {"id": None},
            "cpu": {"enabled": True, "huge-pages": True, "*": {"intensity": 1, "threads": args.threads, "affinity": -1},
                    "rx": [0, 1], "cn/0": False},
            "pools": [{"url": args.url, "user": args.user, "pass": args.password, "tls": args.tls}],
        }
        self.threads = args.threads

    def summary(self):
        with self.lock:
            n = 0 if self.paused else self.threads
            return {
                "uptime": int(time.time() - self.started),
                "paused": self.paused,
                "hashrate": {"total": [100.0 * n, 100.0 * n, None], "threads": [[100.0]] * n},
                "results": {"shares_good": self.shares, "shares_total": self.shares},
                "connection": {"pool": self.config["pools"][0]["url"]},
            }


def main(argv=None):
    args = parse_args(argv)
    state = State(args)
    interval = float(os.environ.get("FAKE_SHARE_INTERVAL", "2"))

    def shares():
        while True:
            time.sleep(interval)
            with state.lock:
                if not state.paused:
                    state.shares += 1

    threading.Thread(target=shares, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, code, obj=None):
            body = b"" if obj is None else json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self):
            if self.headers.get("Authorization") == f"Bearer {args.http_access_token}":
                return True
            self._reply(401, {"error": "unauthorized"})
            return False

        def _body(self):
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")

        def do_GET(self):
            if not self._authorized():
                return
            if self.path == "/1/summary":
                return self._reply(200, state.summary())
            if self.path == "/1/config":
                with state.lock:
                    return self._reply(200, state.config)
            self._reply(404, {"error": "not found"})

        def do_PUT(self):
            if not self._authorized():
                return
            if self.path != "/1/config":
                return self._reply(404, {"error": "not found"})
            if os.environ.get("FAKE_XMRIG_NO_PUT"):
                return self._reply(500, {"error": "nope"})
            cfg = self._body()
            with state.lock:
                state.config = cfg
                star = cfg.get("cpu", {}).get("*")
                if isinstance(star, dict) and not os.environ.get("FAKE_XMRIG_IGNORE_THREADS"):
                    state.threads = int(star.get("threads", state.threads))
            self._reply(204)

        def do_POST(self):
            if not self._authorized():
                return
            if self.path != "/json_rpc":
                return self._reply(404, {"error": "not found"})
            method = self._body().get("method")
            with state.lock:
                if method == "pause":
                    state.paused = True
                elif method == "resume":
                    state.paused = False
                else:
                    return self._reply(200, {"id": 1, "jsonrpc": "2.0", "error": {"code": -32601}})
            self._reply(200, {"id": 1, "jsonrpc": "2.0", "result": "OK"})

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.http_port), Handler)
    except OSError:
        # Like the real XMRig: keep mining without an API when the port is taken.
        print(f"fake xmrig: port {args.http_port} in use, running without API", flush=True)
        while True:
            time.sleep(1)
    print(f"fake xmrig listening on {args.http_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
