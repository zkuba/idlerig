# Migrating from ZenMiner 0.2.x

ZenMiner was renamed to **IdleRig** in 0.3.0. "ZEN" is the ticker of Horizen, a different coin,
which made the old name confusing for a Monero tool.

Your existing start script keeps working after renaming the executable. The checklist below
covers what changed.

## Checklist

1. Replace `ZenMiner-0.2.x.exe` with `IdleRig-0.3.0.exe` in your `.bat` file.
2. Remove `--http-token zenminer`, or choose your own secret. Without the option, IdleRig uses a
   random token and the tray link includes it.
3. If you passed `--donate-level` below 1, it is now raised to 1% with a warning (as before).
4. Logs are now in `logs\idlerig.log` instead of `logs\zenminer.log`.

## Options

| ZenMiner 0.2 | IdleRig 0.3 | Note |
|---|---|---|
| `--logout-after-min` | `--away-after-min` | old name still accepted |
| `--http-port-xmrig` | `--xmrig-http-port` | old name still accepted |
| `--tp` | – | accepted and ignored (had no effect before either) |
| `--http-debug` | `--verbose` | old name still accepted |
| `--xmrig-path` (required) | `--xmrig-path` (optional) | defaults to `xmrig.exe` next to IdleRig, then `PATH` |
| `--logout-after-min` default `15` | `--away-after-min` default `10` | pass `--away-after-min 15` to keep the old timing |
| `-t` default `1` | `-t` default `25%,50%,75%` | pass `-t 1` to keep the old behaviour |
| `-t "1-4"` | – | ranges are no longer accepted; use `1,2,4` |
| – | `--tls`, `--no-huge-pages`, `--xmrig-arg`, `--no-web`, `--log-dir`, `--version` | new |

States are now called `active`, `idle`, `away` (previously `logged_out` for the last one).

## Behaviour changes

- **Huge pages are on by default.** ZenMiner always passed `--no-huge-pages`, which cost roughly
  20–30% hashrate. Use `--no-huge-pages` to keep the old behaviour.
- **Returning to `active` is immediate.** ZenMiner applied the debounce in both directions.
- **Failed live changes now actually fall back to a restart.** ZenMiner checked a `(ok, message)`
  tuple as a boolean. Failed thread changes were therefore logged as successful and never
  retried.
- **The dev slice always mines on `pool.supportxmr.com`**, under an anonymous per-user worker
  name, and lasts until at least one share is accepted (max 20 min). See [dev-fee.md](dev-fee.md).
- **Web API.** Endpoints moved under `/api/` and all of them require the token:
  - `/status` → `/api/status`;
  - `/control` → `/api/control`;
  - `/log_lines` → `/api/logs`;
  - `/download_log` → `/api/download/app`;
  - `/download_xmrig` → `/api/download/xmrig`;
  - the `rotate_now` action was removed.
- **Flask is no longer used.** The web server is part of Python's standard library.
- **XMRig's API token is random per run.** Previously it was `zenminer`, which let any local
  program reconfigure the miner.
