# Building and development

## Requirements

- Windows 10/11 x64 (IdleRig runs elsewhere too, but activity detection is Windows-only)
- Python 3.10 or newer
- For the `.exe`: a C compiler. Nuitka downloads MinGW automatically if none is found.

## Set up

```powershell
git clone https://github.com/zkuba/idlerig.git
cd idlerig
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
```

## Run from source

```powershell
.venv\Scripts\python -m idlerig --wallet <YOUR_WALLET> --xmrig-path C:\xmrig\xmrig.exe
```

Without real mining, use the fake XMRig that the tests use. It serves the same API and
"finds" a share every 2 seconds:

```powershell
.venv\Scripts\python -m idlerig --wallet <ANY_MONERO_ADDRESS> --xmrig-path tests\fake_xmrig.py `
    --http-token dev --idle-after-min 0.2 --away-after-min 0.5 --state-debounce-sec 3
```

Then open `http://127.0.0.1:5515/#token=dev`. Leave the mouse alone for 12 s to see the `idle`
transition.

Check activity detection on your machine (lock the screen with `Win+L` while it runs):

```powershell
.venv\Scripts\python -m idlerig.activity
```

## Tests

```powershell
.venv\Scripts\python -m pytest -q
```

| File | Covers |
|---|---|
| `tests/test_threads.py` | `--threads` parsing and resolution |
| `tests/test_governor.py` | State machine, debounce, immediate return to `active` (fake clock) |
| `tests/test_rotator.py` | Dev-fee schedule table, alternation, share guarantee, worker name |
| `tests/test_xmrig.py` | Real child process (`fake_xmrig.py`): live thread/pool changes, API failure → restart, unconfirmed change → restart, pause/resume, watchdog and back-off |
| `tests/test_web.py` | Auth (401/403), status, control actions, incremental logs, downloads |
| `tests/test_cli.py` | Options, legacy flags, placeholder wallet, XMRig discovery |

`fake_xmrig.py` can simulate failures with environment variables:

- `FAKE_XMRIG_NO_PUT=1`: config changes fail;
- `FAKE_XMRIG_IGNORE_THREADS=1`: thread changes are accepted but not applied.

## Build the .exe

```powershell
.\build.ps1
```

The script:

1. reads the version from `idlerig/__init__.py`;
2. runs the tests and stops if any fail;
3. generates `build\idlerig.ico` from `idlerig/icon.py`;
4. builds `dist\IdleRig-<version>.exe` with Nuitka: one file, no console window, with that icon
   and the web UI embedded;
5. optionally signs it (`-PfxPath cert.pfx -PfxPassword (Read-Host -AsSecureString)`);
6. writes `dist\CHECKSUMS.txt` (SHA-256).

A first build takes several minutes. Later builds are faster thanks to Nuitka's cache.

## Releasing

1. Bump `__version__` in `idlerig/__init__.py` (the only place the version lives).
2. Add a section to `CHANGELOG.md`.
3. `.\build.ps1`
4. Tag `vX.Y.Z` and attach the `.exe`, `CHECKSUMS.txt` and both `.bat.example` files to the
   GitHub release.

## Code layout

See [how-it-works.md](how-it-works.md#how-idlerig-works) for the module overview.

Conventions:

- **Standard library only** in `idlerig/`, except the optional tray (`pystray`, `Pillow`).
- **Explicit results.** Functions that talk to XMRig return `bool` or `None` on failure and never
  raise for network errors. Callers decide whether to fall back to a restart.
- **One owner of XMRig changes.** Everything that changes XMRig goes through `Miner` in
  `idlerig/xmrig.py`.
- **Logs and UI in English.**
