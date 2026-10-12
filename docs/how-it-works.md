# How IdleRig works

IdleRig is a small supervisor around XMRig. It never mines itself: it starts `xmrig.exe`,
watches what you are doing, and tells XMRig how much CPU it may use and which wallet it is
mining for.

```
             ┌──────────────┐  idle seconds,   ┌─────────────┐
 Windows ───▶│  activity.py │──── locked? ────▶│ governor.py │──┐ set_threads(n)
             └──────────────┘                  └─────────────┘  │
                                                                ▼
             ┌──────────────┐  set_identity(pool, wallet) ┌───────────┐  HTTP API   ┌───────┐
             │  rotator.py  │────────────────────────────▶│ xmrig.py  │────────────▶│ XMRig │
             └──────────────┘                             │  (Miner)  │  restart    └───────┘
                                                          └───────────┘◀── watchdog
             ┌──────────────┐  status / control                ▲
 Browser ───▶│    web.py    │──────────────────────────────────┘
             └──────────────┘
```

| Module | Responsibility |
|---|---|
| `idlerig/activity.py` | Seconds since last input (`GetLastInputInfo`) and lock-screen detection |
| `idlerig/threads.py` | Parses `--threads` and turns a state into a thread count |
| `idlerig/governor.py` | Activity state machine with debounce; also runs the XMRig watchdog |
| `idlerig/rotator.py` | Dev-fee schedule and wallet/pool switching |
| `idlerig/xmrig.py` | Starts/stops XMRig, talks to its HTTP API, falls back to restarts |
| `idlerig/web.py` | Local web UI and JSON API |
| `idlerig/tray.py` | Optional tray icon |
| `idlerig/cli.py` | Command-line options and start-up/shut-down order |

## Activity states

Once per second the governor reads two signals:

- **idle time**: seconds since the last keyboard or mouse input in your session;
- **locked**: whether the lock screen (or another secure desktop, such as a UAC prompt) is shown.

| State | Condition | Threads (from `--threads a,b,c`) |
|---|---|---|
| `away` | locked, **or** idle ≥ `--away-after-min` | `c` |
| `idle` | idle ≥ `--idle-after-min` | `b` |
| `active` | otherwise | `a` |

```
            idle ≥ 2 min (held 10 s)        idle ≥ 10 min or locked (held 10 s)
  active ───────────────────────────▶ idle ─────────────────────────────────▶ away
     ▲                                  │                                      │
     └──────── any input (immediate) ───┴──────────────────────────────────────┘
```

- **Debounce.** A move to a *lower-activity* state (`active` → `idle` → `away`) is applied only
  after it has been observed continuously for `--state-debounce-sec` (default 10 s).
- **Coming back is immediate.** Any input switches back to `active` without waiting, so the
  machine is responsive as soon as you return.
- **Detection failure is safe.** If Windows calls fail, the state is `active` (fewest threads).
- **Other platforms.** On non-Windows systems idle time is always 0, so IdleRig stays `active`.

A thread count of `0` **pauses** XMRig (through its `pause` API) instead of stopping it. Resuming
is then instant, because the RandomX dataset stays in memory.

## Applying changes to XMRig

XMRig is started with its HTTP API on `127.0.0.1` and a random access token that only IdleRig
knows. Every change is tried live first:

| Change | API call | Confirmation | Fallback |
|---|---|---|---|
| Thread count | `GET /1/config`, set `cpu["*"].threads`, `PUT /1/config` | `/1/summary` reports the new number of threads (≤ 15 s) | restart with `--threads=N` |
| Pool / wallet / worker | `GET /1/config`, set `pools[0]`, `PUT /1/config` | HTTP 2xx | restart with new `--url/--user/--pass` |
| Pause / resume | `POST /json_rpc` `pause` / `resume` | JSON-RPC result | stop the process / restart |

Why `cpu["*"]`: when started with `--threads=N`, XMRig stores the thread profile as
`cpu["*"] = {"intensity", "threads", "affinity"}`. IdleRig updates that profile. Any
algorithm-specific profile (for example an `rx` list created by XMRig's auto-configuration) is
pointed at `"*"`, so it cannot override the setting.

All changes go through a single `Miner` object protected by a lock. A restart always uses the
*current* thread count and identity, so the governor, the rotator and the web UI cannot undo
each other's changes.

### Watchdog

If XMRig exits while it should be running, it is restarted:

- the first time immediately;
- after repeated crashes with growing delays (5 s, 10 s, 20 s, … up to 5 minutes);
- the counter resets after XMRig has run for 60 s.

## Dev-fee rotation

The rotator alternates between your pool/wallet and the developer's. See [dev-fee.md](dev-fee.md)
for the schedule. Switching is a pool change (see the table above) and does not affect the thread
count.

## Start-up and shut-down order

1. Parse options, set up logging in `logs/`.
2. Read the current activity state and start XMRig with the matching thread count, so there is no
   restart a second later.
3. Wait until XMRig's API answers, then start the rotator and the governor.
4. Start the web UI and the tray icon.
5. On Ctrl+C, the tray's **Exit**, or a termination signal: stop the rotator and governor, stop
   XMRig, close the web server.

## Files written

| File | Content |
|---|---|
| `logs/idlerig.log` | IdleRig log (rotated at 5 MB, 3 backups) |
| `logs/xmrig.log` | XMRig's own log (`--log-file`): hashrate, pool messages, huge pages |
| `logs/xmrig_console.log` | Anything XMRig prints before its log is open, such as argument errors |

XMRig is placed in a Windows job object that is closed when IdleRig's process ends. If IdleRig
exits in any way, including a crash or Task Manager, Windows terminates XMRig too, so it can
never keep mining unattended.

IdleRig does not write any configuration file and does not change system settings.
