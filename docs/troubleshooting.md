# Troubleshooting

Start with the logs in the `logs` folder next to `IdleRig.exe`:

- `idlerig.log`: what IdleRig decided and why (state changes, switches, restarts);
- `xmrig.log`: XMRig's own log (hashrate, pool messages, huge-page status);
- `xmrig_console.log`: messages XMRig printed before its log was open, such as argument errors.

Add `--verbose` for more detail.

## IdleRig exits immediately

| Message | Fix |
|---|---|
| `set --wallet to your own Monero address` | Replace `YOUR_WALLET` in your `.bat` file. |
| `XMRig not found` | Put `xmrig.exe` next to `IdleRig.exe` or pass `--xmrig-path C:\full\path\xmrig.exe`. |
| `--threads: …` | See [thread syntax](configuration.md#thread-syntax). In `.bat` files write `%%` for `%`. |
| `Cannot open web UI port 5515` | Another IdleRig (or another program) uses the port. Exit the other instance or pass `--http-port`. |

## XMRig keeps restarting

The log shows `XMRig is not running (exit code …); restarting in …s`. Check `xmrig_console.log`
and `xmrig.log`. Common causes:

- **Antivirus removed or blocked `xmrig.exe`.** Most antivirus products flag miners. Add an
  exclusion for the XMRig folder, or download XMRig again.
- **Port 18080 in use** (XMRig cannot start its API). Pass `--xmrig-http-port 18081`.
- **Wrong XMRig build.** Use the official `xmrig-<version>-msvc-win64.zip` or `-gcc-win64.zip`.
- **Huge-pages problems.** Rare, but if XMRig crashes right after `huge pages` messages, try
  `--no-huge-pages`.

## Low hashrate

- **Huge pages are not enabled.** `xmrig.log` says `huge pages 0%`. On Windows, huge pages
  need the *Lock pages in memory* privilege. Run XMRig **once as administrator**: it grants the
  privilege to your account, then sign out and back in. After that, `huge pages 100%` should
  appear without admin rights.
- **`FAILED TO APPLY MSR MOD, HASHRATE WILL BE LOW`.** XMRig can tune CPU registers (MSR) for
  RandomX, which needs administrator rights on every start. Without them you lose roughly 10–15%.
  If you want this, run IdleRig as administrator. Its child XMRig inherits the rights.
- **Too many threads.** RandomX needs about 2 MB of L3 cache per thread. Beyond that, extra
  threads add heat but not hashrate. Compare `away` at 50%, 75% and 100% in the web UI chart.
- **You are looking at the `active` state.** Leave the computer alone, or lock it (`Win+L`), and
  watch the state change.

## The state never leaves `active`

- **Something keeps generating input.** Some mouse drivers, remote-desktop tools and games do this.
  Run `python -m idlerig.activity` (from source) to watch the idle counter.
- **IdleRig runs in a different session.** For example as a service or a scheduled task "whether
  the user is logged on or not". It must run in your interactive session; see
  [Start with Windows](configuration.md#start-with-windows).
- **Not Windows.** Activity detection is only implemented for Windows.

## The state is `away` while I am working

A secure desktop (UAC prompt, Ctrl+Alt+Del screen) counts as locked while it is shown. If it
happens otherwise, run the activity diagnostic above and open an issue with its output.

## No tray icon

- `--no-tray` or `--no-web` was given. The tray needs the web UI for its **Open web UI** item.
- Running from source without `pystray` and `Pillow`: `pip install -r requirements.txt`.
- Windows hides new tray icons in the overflow area (`^`). Drag it to the taskbar.

## The web UI asks for a token

The token changes on every start unless you pass `--http-token`. Open the UI from the tray, or
copy the `Web UI access:` link from `logs/idlerig.log`.

## Thread changes cause restarts

The log says `Applying N threads via API failed; restarting XMRig` or
`XMRig still reports X threads after setting N`.

- **Very old XMRig.** Use XMRig 6.x.
- **`config.json` with a fixed CPU profile next to `xmrig.exe`.** IdleRig overrides CPU profiles
  through the API, but an unusual `config.json` can still interfere. Remove or rename it; IdleRig
  passes everything XMRig needs on the command line.

Restarts still work; they only cost a few seconds of hashrate each time.
