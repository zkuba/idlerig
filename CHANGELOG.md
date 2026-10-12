# Changelog

## 0.3.0 (unreleased)

ZenMiner is now **IdleRig**. See [docs/migration-from-zenminer.md](docs/migration-from-zenminer.md).

### Fixed

- **Failed thread changes are no longer reported as successful.** The result tuple was used as
  a boolean, so the restart fallback never ran.
- **Huge pages are no longer disabled.** About 20–30% more RandomX hashrate.
- **Activity detection keeps working after 49.7 days of uptime.** The idle time mixed 64-bit and
  32-bit tick counters.
- **The rotator no longer races XMRig start-up.** Restarts always use the current wallet and
  thread count.
- **Relative `--xmrig-path` works.** XMRig now runs with its own folder as working directory.

### Changed

- **Rewritten as the `idlerig` package**, with modules for activity, threads, governor, rotator,
  XMRig, web and tray, plus 60+ tests against a fake XMRig.
- **Web UI rewritten.**
  - English only, no CDN.
  - Built-in hashrate chart, light/dark theme.
  - Incremental log view.
  - Dev-fee panel.
- **Flask removed;** the standard library HTTP server is used instead.
- **Dev fee.**
  - Always mined on `pool.supportxmr.com:3333`.
  - Anonymous worker `idlerig-<version>-<hash>`.
  - Each dev slice lasts until at least one share is accepted (max 20 min).
  - Documented in [docs/dev-fee.md](docs/dev-fee.md).
- **Returning to `active` is applied immediately;** only lower-activity states are debounced.
- **Default thread spec is `25%,50%,75%`** (was `1`).
- **`away` starts after 10 minutes without input** (was 15). Returning to `active` is immediate, so
  the shorter delay costs nothing when you come back.
- **Example start scripts use a `YOUR_WALLET` placeholder,** and IdleRig refuses to start with it.
- **Documentation rewritten in English** under `docs/`.

### Added

- **Thread value `0`** pauses mining in that state (XMRig `pause`, instant resume).
- **Watchdog** restarts XMRig if it crashes, with exponential back-off.
- **New options:** `--tls`, `--no-huge-pages`, `--xmrig-arg`, `--no-web`, `--log-dir`,
  `--verbose`, `--version`.
- **`--xmrig-path` is optional;** `xmrig.exe` next to IdleRig or on `PATH` is found automatically.
- **Application icon** (CPU chip with a crescent moon) for the tray, the .exe and the web UI.
  - The tray colour shows the state: teal = mining for you, amber = dev slice, grey = paused/stopped.
  - The tray menu shows the current status.
- **"CPU usage" card in the web UI.**
  - One field per state, with a live explanation such as "4 of 16 threads (≈ 25% of CPU)".
  - The current state is highlighted.
- **XMRig is tied to IdleRig's lifetime** through a Windows job object. It can no longer keep
  mining as an orphan after IdleRig crashes or is killed.
- **Port conflicts are detected.** If another XMRig already holds the API port, IdleRig reports
  it instead of running an uncontrollable second miner.
- **XMRig output goes to `logs/xmrig.log`** via XMRig's own `--log-file`. On Windows XMRig writes
  nothing to a redirected stdout.
- **The log records who started or stopped mining** (tray or web UI).

### Security

- **XMRig's API token is random per run** (was the fixed `zenminer`).
- **All web API endpoints require the token,** including status, logs and downloads.
- **Requests with a non-loopback `Host` header are rejected** (DNS-rebinding protection).
- **The web UI token is random per run** unless `--http-token` is given.

## 0.2.1

- Adaptive state timing options (`--idle-after-min`, `--logout-after-min`, `--state-debounce-sec`).
- Console / no-console `.bat` examples.

## 0.2.0

- Web UI with hashrate chart, log viewer and token control.
- Wallet rotation with dev fee; repository clean-up.

## 0.0.1

- First version: XMRig controller with REST API and tray icon.
