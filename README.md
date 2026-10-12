# IdleRig

**Mine Monero with the CPU time you are not using.**

IdleRig runs [XMRig](https://github.com/xmrig/xmrig) for you on Windows and changes how
many CPU threads it may use depending on whether you are at the computer:

| You are…                               | State    | Default threads |
|----------------------------------------|----------|-----------------|
| working (recent keyboard/mouse input)  | `active` | 25% of CPUs     |
| away for 2+ minutes                    | `idle`   | 50%             |
| away for 10+ minutes, or screen locked | `away`   | 75%             |

When you come back, IdleRig switches to `active` immediately so your machine is responsive again.
Changes are applied live through XMRig's HTTP API, without restarting the miner.

> Formerly **ZenMiner**. It was renamed because "ZEN" is the ticker of an unrelated coin
> (Horizen). See [migration notes](docs/migration-from-zenminer.md).

## Features

- **Activity-aware threads.** Uses Windows input and lock-screen detection. Values can be absolute (`2,4,8`) or percentages (`25%,50%,100%`), and `0` pauses mining while you work.
- **Live changes, no restarts.** Thread count and pool are changed through XMRig's API. If the API is unavailable or a change cannot be confirmed, IdleRig restarts XMRig.
- **Watchdog.** If XMRig crashes, IdleRig restarts it with back-off.
- **No orphaned miners.** XMRig always stops together with IdleRig, even if IdleRig crashes or is killed from Task Manager.
- **Local web UI** at `http://127.0.0.1:5515/`.
  - Shows hashrate, shares, activity state, the dev-fee status and a live log.
  - Lets you start and stop mining and change settings.
  - A **CPU usage** card explains each level in plain terms, for example "4 of 16 threads (≈ 25% of CPU)".
- **Tray icon.** IdleRig lives in the notification area. Teal means mining for you, amber means dev-fee slice, grey means paused or stopped. The menu shows the current status.
- **Small and dependency-light.** Python standard library only; the tray icon optionally uses `pystray` and `Pillow`.

## Quick start

1. Download `IdleRig-<version>.exe` from the releases page and get
   [XMRig](https://github.com/xmrig/xmrig/releases) (the `msvc-win64` zip). Put `xmrig.exe` in
   the same folder.
2. Copy `run_idlerig.bat.example` to `run_idlerig.bat` and set `WALLET` to **your** Monero address.
3. Run `run_idlerig.bat`. A tray icon appears; choose **Open web UI**.

Or straight from a terminal:

```powershell
.\IdleRig-0.3.0.exe --wallet <YOUR_MONERO_ADDRESS> --threads "25%,50%,100%"
```

From source (Python 3.10+):

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m idlerig --wallet <YOUR_MONERO_ADDRESS> --xmrig-path C:\xmrig\xmrig.exe
```

## Dev fee

By default IdleRig mines **2%** of the time for the developer: about 7 minutes every
5 h 50 min, on `pool.supportxmr.com`. The minimum is 1%. The web UI always shows the dev
wallet, the current owner and when the next switch happens.

The dev slice uses an anonymous worker name (`idlerig-<version>-<hash>`). This lets the developer
see how many installations are running, without learning your wallet.
Details: [docs/dev-fee.md](docs/dev-fee.md).

## Documentation

| Topic | |
|---|---|
| [How it works](docs/how-it-works.md) | States, thresholds, rotation, XMRig API |
| [Configuration](docs/configuration.md) | All command-line options, thread syntax, start scripts, autostart |
| [Dev fee](docs/dev-fee.md) | Schedule formula, dev pool, worker naming |
| [Web UI and API](docs/web-ui-and-api.md) | UI tour, endpoints, authentication |
| [Building](docs/building.md) | Development setup, tests, building the .exe |
| [Troubleshooting](docs/troubleshooting.md) | Huge pages, antivirus, ports, logs |
| [Migrating from ZenMiner](docs/migration-from-zenminer.md) | Renamed files and options |
| [Changelog](CHANGELOG.md) | |

## Responsible use

Only run IdleRig on computers you own or are explicitly allowed to mine on. Mining increases
power use and heat. On laptops, consider low `active`/`idle` values or `0` to pause.

## License

[MIT](LICENSE)
