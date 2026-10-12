# Configuration

IdleRig is configured entirely with command-line options. Usually you put them in a start script
(see [Start scripts](#start-scripts)). Run `IdleRig.exe --help` for the built-in summary.

## Options

### Mining

| Option | Default | Description |
|---|---|---|
| `-u`, `--wallet ADDRESS` | **required** | Your Monero address. Pool-specific suffixes such as `ADDRESS.paymentid` or `ADDRESS+diff` are passed through. |
| `-o`, `--pool HOST:PORT` | `pool.supportxmr.com:3333` | Pool to mine on for yourself. |
| `-p`, `--worker NAME` | computer name | Worker name shown on the pool dashboard (sent as the pool password, the usual convention). |
| `--tls` | off | Use TLS to connect to the pool (needed for TLS ports such as `:443` on many pools). |
| `--xmrig-path PATH` | `xmrig.exe` next to IdleRig, then `PATH` | Location of XMRig. Relative paths are resolved against the current directory, then IdleRig's folder, then `PATH`. |
| `--xmrig-arg ARG` | – | Extra argument for XMRig. Repeat for several, e.g. `--xmrig-arg=--cpu-priority=1 --xmrig-arg=--randomx-1gb-pages`. |
| `--no-huge-pages` | off | Start XMRig with `--no-huge-pages`. Huge pages make RandomX roughly 20–30% faster; disable them only if XMRig fails to start. |
| `--donate-level PERCENT` | `2` | Dev fee, 1–100. Values outside this range are clamped. See [dev-fee.md](dev-fee.md). |

### Activity

| Option | Default | Description |
|---|---|---|
| `-t`, `--threads SPEC` | `25%,50%,75%` | Threads for `active,idle,away`. See [Thread syntax](#thread-syntax). |
| `--idle-after-min MIN` | `2` | Minutes without input before `idle`. Fractions allowed (`0.5` = 30 s). |
| `--away-after-min MIN` | `10` | Minutes without input before `away`. A locked screen is always `away`. Old name: `--logout-after-min`. |
| `--state-debounce-sec SEC` | `10` | How long a lower-activity state must hold before it is applied. Returning to `active` is always immediate. |

### Interface

| Option | Default | Description |
|---|---|---|
| `--http-port PORT` | `5515` | Web UI port (bound to 127.0.0.1 only). |
| `--http-token TOKEN` | random per run | Access token for the web UI/API. When omitted, a random token is generated, written to the log, and included in the tray's **Open web UI** link. |
| `--no-web` | off | Do not start the web UI (the tray icon needs it, so it is disabled too). |
| `--no-tray` | off | Do not show the tray icon. |
| `--xmrig-http-port PORT` | `18080` | Port for XMRig's own API (127.0.0.1). Change it if 18080 is taken or you run two instances. Old name: `--http-port-xmrig`. |
| `--log-dir DIR` | `logs` next to the exe (or the current directory when run from source) | Where logs are written. |
| `-v`, `--verbose` | off | Debug logging. |
| `--version` | | Print the version and exit. |

Accepted but ignored, for compatibility with ZenMiner 0.2: `--tp`, `--http-debug` (now the same as
`--verbose`).

## Thread syntax

`--threads` takes one to three comma-separated values for `active,idle,away`:

| Value | Meaning |
|---|---|
| `4` | exactly 4 threads (capped at the number of logical CPUs) |
| `50%` | half of the logical CPUs, rounded, at least 1 |
| `0` or `0%` | pause mining in this state |

Missing values repeat the last one:

| Spec | active | idle | away (on 8 logical CPUs) |
|---|---|---|---|
| `2` | 2 | 2 | 2 |
| `1,4` | 1 | 4 | 4 |
| `25%,50%,100%` | 2 | 4 | 8 |
| `0,50%,100%` | paused | 4 | 8 |

> In `.bat` files every `%` must be doubled: `set THREADS=25%%,50%%,100%%`.

Rules of thumb:

- Using all logical CPUs rarely helps. RandomX is limited by L3 cache (about 2 MB per
  thread), so try `away` at 50–75% first and compare the hashrate in the web UI.
- Keep `active` low (1–2 threads or `0`) on machines you work on.

## Start scripts

Two examples ship with IdleRig:

| File | Behaviour |
|---|---|
| `run_idlerig.bat.example` | A command window stays open while IdleRig runs. |
| `run_idlerig_hidden.bat.example` | Starts IdleRig in the background with no window; control it from the tray. |

Copy one to a `.bat` file (the real `.bat` files are git-ignored), set `WALLET`, and run it.
IdleRig refuses to start while the wallet is still `YOUR_WALLET`.

## Start with Windows

1. Press `Win+R`, type `shell:startup`, Enter.
2. Create a shortcut there to your `run_idlerig_hidden.bat`.

IdleRig needs your interactive session to detect activity. Start it at **logon** (as above), not
as a service or a "run whether user is logged on or not" scheduled task.

## Running more than one instance

Each instance needs its own `--http-port` and `--xmrig-http-port`. Otherwise the second instance
reports that the port is in use.
