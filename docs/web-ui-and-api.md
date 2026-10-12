# Web UI and API

IdleRig serves a small web UI and JSON API on `http://127.0.0.1:5515/` (`--http-port`). It listens
on the loopback interface only and cannot be reached from other machines.

## Opening the UI

Use the tray icon → **Open web UI**. The link carries the access token in the URL fragment
(`/#token=…`). The page stores the token in the browser's local storage and removes it from the
address bar. Fragments are never sent to the server or written to logs.

Without the tray:

- with `--http-token`, open `http://127.0.0.1:5515/` and enter that token when asked;
- without it, copy the `Web UI access: http://127.0.0.1:5515/#token=…` line from
  `logs/idlerig.log`.

## What the UI shows

| Card | Content |
|---|---|
| **Miner** | Hashrate, running/paused, threads (e.g. "4 of 16 threads (≈ 25% of CPU)"), accepted/rejected shares, uptime, current pool and worker, restart count |
| **Activity** | Current state, idle time or "screen locked", current CPU use, thresholds, logical CPUs |
| **CPU usage** | One field per state (while you work / short break / away). Each field shows live how many threads it means and what share of the CPU that is; the current state is highlighted. Accepts a thread count (`2`), a percentage (`50%`) or `0` to pause. |
| **Dev fee** | Who is being mined for, countdown, fee and schedule, dev pool/wallet/worker, dev slices and shares this session |
| **Hashrate** | Chart of the last 10 minutes (sampled every 3 s) |
| **Controls** | Start, Stop, Restart XMRig; change your pool and worker |
| **Log** | Live `idlerig.log` with filter, follow mode and downloads of `idlerig.log` / `xmrig.log` |

Changes made in the UI last until IdleRig exits. Put permanent settings in your start script.

The UI follows the system light/dark theme and needs no internet access (no CDN, fonts or
trackers).

## Authentication

Every `/api/*` request needs the token, in any of these forms:

```
Authorization: Bearer <token>
X-Auth-Token: <token>
?token=<token>
```

- **Host check.** Requests whose `Host` header is not `127.0.0.1`, `localhost` or `[::1]` are
  rejected with `403` (protection against DNS rebinding).
- **No CORS.** The API sends no CORS headers, so other websites open in your browser cannot read
  it or send authenticated requests to it.
- **Separate XMRig token.** XMRig's own API uses a separate random token per run that only
  IdleRig knows.

## Endpoints

### `GET /api/status`

```json
{
  "version": "0.3.0",
  "miner": {
    "running": true, "paused": false, "pid": 1234, "threads": 4, "uptime": 812, "restarts": 0,
    "hashrate": 2150.4, "shares": {"accepted": 12, "rejected": 0, "total": 12},
    "pool": "pool.supportxmr.com:3333", "wallet": "4…", "worker": "MYPC"
  },
  "activity": {
    "state": "idle", "idle_seconds": 245, "locked": false, "threads_spec": "25%,50%,75%",
    "idle_after": 120.0, "away_after": 900.0, "debounce": 10.0, "cpu_count": 16
  },
  "user": {"pool": "pool.supportxmr.com:3333", "wallet": "4…", "worker": "MYPC"},
  "dev_fee": {
    "owner": "user", "seconds_to_next": 20100, "waiting_for_share": false,
    "percent": 2.0, "dev_minutes": 7.0, "cycle_minutes": 350.0,
    "dev_wallet": "87Qd…", "dev_pool": "pool.supportxmr.com:3333",
    "dev_worker": "idlerig-0.3.0-1a2b3c4d", "dev_dashboard": "https://supportxmr.com/#/dashboard?wallet=87Qd…",
    "dev_slices": 1, "dev_shares": 2
  }
}
```

Field notes:

- `miner.*` describes what XMRig is doing *now*, so during a dev slice it shows the dev pool and
  wallet. `user.*` is always your own configuration.
- `hashrate` is in H/s (most recent of XMRig's 10 s / 60 s / 15 min averages), or `null`.
- `state` is `active`, `idle`, `away` or `null` (during start-up).

### `GET /api/logs?since=<offset>`

Returns new complete lines of `idlerig.log` after byte `offset`, plus the next offset:

```json
{"offset": 48211, "lines": ["2026-10-12 21:23:15,344 [INFO] idlerig.governor: Activity active -> idle …"]}
```

- Use `since=-1` to get the last ~64 KB.
- If the log was rotated, the server returns the tail of the new file and a smaller offset;
  clients should then clear their buffer.

### `GET /api/download/app`, `GET /api/download/xmrig`

Download `idlerig.log` or `xmrig.log` as an attachment.

### `POST /api/control`

JSON body with an `action`:

| Body | Effect |
|---|---|
| `{"action": "start"}` | Start XMRig |
| `{"action": "stop"}` | Stop XMRig (the watchdog will not restart it) |
| `{"action": "restart"}` | Restart XMRig |
| `{"action": "set_threads", "threads": "1,50%,100%"}` | Replace the thread spec and apply it to the current state |
| `{"action": "set_pool", "pool": "host:port", "worker": "name"}` | Change your pool and/or worker (either may be omitted) |

Responses are `{"ok": true, …}` or `{"ok": false, "error": "…"}`. Status codes:

- `400`: invalid input;
- `401`: missing or wrong token;
- `403`: foreign `Host` header.

## Examples

```powershell
$h = @{ Authorization = "Bearer my-token" }
Invoke-RestMethod http://127.0.0.1:5515/api/status -Headers $h

Invoke-RestMethod http://127.0.0.1:5515/api/control -Method Post -Headers $h `
  -ContentType application/json -Body '{"action":"set_threads","threads":"0,50%,100%"}'
```

```bash
curl -H "Authorization: Bearer my-token" http://127.0.0.1:5515/api/status
```
