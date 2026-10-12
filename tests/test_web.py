import http.client
import json

import pytest

from idlerig.governor import Governor
from idlerig.rotator import DEV_WALLET, Rotator
from idlerig.threads import ThreadSpec
from idlerig.web import Services, WebServer
from idlerig.xmrig import PoolIdentity

USER = PoolIdentity("pool.example:3333", "4" + "B" * 94, "pc")
TOKEN = "secret-token"


class StubMiner:
    identity = USER
    paused = False
    pid = None
    threads = 2
    started_at = None
    restarts = 0
    on_change = None

    def __init__(self):
        self.actions = []

    def is_running(self):
        return False

    def summary(self):
        return None

    def start(self, source=None):
        self.actions.append("start")
        return True

    def stop(self, source=None):
        self.actions.append("stop")

    def restart(self, source=None):
        self.actions.append("restart")
        return True

    def set_threads(self, n):
        self.actions.append(("threads", n))

    def set_identity(self, ident):
        self.actions.append(("identity", ident))


@pytest.fixture
def server(port, tmp_path):
    miner = StubMiner()
    gov = Governor(miner, ThreadSpec.parse("1,2,4"), 120, 900, 10)
    gov.state = "active"
    rot = Rotator(miner, USER, 2)
    (tmp_path / "idlerig.log").write_text("line one\nline two\n", encoding="utf-8")
    srv = WebServer(Services(miner, gov, rot, tmp_path), port, TOKEN)
    srv.start()
    yield srv, miner, gov, rot, tmp_path
    srv.stop()


def request(srv, method, path, token=TOKEN, body=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if host:
        headers["Host"] = host
    data = None
    if body is not None:
        data = json.dumps(body)
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=headers)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        return resp.status, json.loads(raw)
    except ValueError:
        return resp.status, raw


def test_index_is_public(server):
    srv = server[0]
    code, body = request(srv, "GET", "/", token=None)
    assert code == 200 and b"IdleRig" in body


def test_favicon_is_public(server):
    code, body = request(server[0], "GET", "/favicon.svg", token=None)
    assert code == 200 and body.startswith(b"<svg")


def test_api_requires_token(server):
    srv = server[0]
    assert request(srv, "GET", "/api/status", token=None)[0] == 401
    assert request(srv, "GET", "/api/status", token="wrong")[0] == 401
    assert request(srv, "POST", "/api/control", token=None, body={"action": "stop"})[0] == 401


def test_query_token_is_accepted(server):
    srv = server[0]
    assert request(srv, "GET", f"/api/status?token={TOKEN}", token=None)[0] == 200


def test_foreign_host_is_rejected(server):
    srv = server[0]
    assert request(srv, "GET", "/api/status", host="evil.example:5515")[0] == 403


def test_status(server):
    srv = server[0]
    code, st = request(srv, "GET", "/api/status")
    assert code == 200
    assert st["dev_fee"]["dev_wallet"] == DEV_WALLET
    assert st["activity"]["threads_spec"] == "1,2,4"
    assert st["user"]["wallet"] == USER.wallet


def test_control_actions(server):
    srv, miner, gov, rot, _ = server
    for action in ("start", "stop", "restart"):
        assert request(srv, "POST", "/api/control", body={"action": action})[0] == 200
    code, r = request(srv, "POST", "/api/control", body={"action": "set_threads", "threads": "3,3,3"})
    assert code == 200 and str(gov.spec) == "3,3,3" and ("threads", 3) in miner.actions
    assert request(srv, "POST", "/api/control", body={"action": "set_threads", "threads": "zzz"})[0] == 400
    assert request(srv, "POST", "/api/control", body={"action": "set_pool", "worker": "new"})[0] == 200
    assert rot.user.worker == "new" and rot.user.wallet == USER.wallet
    assert request(srv, "POST", "/api/control", body={"action": "nope"})[0] == 400
    assert miner.actions[:3] == ["start", "stop", "restart"]


def test_incremental_logs(server):
    srv, *_, log_dir = server
    code, r = request(srv, "GET", "/api/logs?since=-1")
    assert r["lines"] == ["line one", "line two"]
    with open(log_dir / "idlerig.log", "a", encoding="utf-8") as f:
        f.write("line three\npartial")
    code, r2 = request(srv, "GET", f"/api/logs?since={r['offset']}")
    assert r2["lines"] == ["line three"]
    code, r3 = request(srv, "GET", f"/api/logs?since={r2['offset']}")
    assert r3["lines"] == []


def test_download(server):
    srv = server[0]
    code, body = request(srv, "GET", "/api/download/app")
    assert code == 200 and b"line one" in body
    assert request(srv, "GET", "/api/download/xmrig")[0] == 404
