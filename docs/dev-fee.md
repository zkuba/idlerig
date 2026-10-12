# Dev fee

IdleRig is free and open source. To support development, and to let the developer see that people
actually use it, IdleRig mines a small share of the time for the developer's wallet. This page
explains exactly how.

## What happens

- **2% of the time by default.** IdleRig switches to the developer's wallet for a short *dev
  slice*, then back to yours.
- **Always on `pool.supportxmr.com:3333`.** During a dev slice IdleRig mines there, whatever pool
  you use, so all contributions show up in one place. When the slice ends, your own pool and
  wallet are restored.
- **Thread count is unchanged.** It still follows your activity state.
- **XMRig's built-in donation is off.** IdleRig passes `--donate-level=0` to XMRig, so the dev
  slice is the only fee.

| Constant | Value |
|---|---|
| Dev wallet | `87QdreCSsmVC3s9SzctnPuMuEfupAivfdHCstLCKvQQiWtkhfoJFWH1fUMxu3am7Lh9eRHfKPVf5Gi5aKemLqBNpTEEc6oj` |
| Dev pool | `pool.supportxmr.com:3333` |
| Public dashboard | [supportxmr.com dashboard for the dev wallet](https://supportxmr.com/#/dashboard?wallet=87QdreCSsmVC3s9SzctnPuMuEfupAivfdHCstLCKvQQiWtkhfoJFWH1fUMxu3am7Lh9eRHfKPVf5Gi5aKemLqBNpTEEc6oj) |

All of these are defined at the top of `idlerig/rotator.py`.

## Schedule

For a fee of **D** percent (`--donate-level`, 1–100):

```
dev slice  S = min(15 min, floor(6 h × D / 100)), at least 1 min
cycle        = S × 100 / D        (never longer than 6 h)
user slice   = cycle − S
first user slice = min(user slice, 15 min)
```

Capping the cycle at 6 hours keeps slices short and frequent. Your share of mining time
stays the same; the dev time is just spread out evenly.

| Fee | Dev slice | User slice | Cycle |
|---|---|---|---|
| 1% | 3 min | 4 h 57 min | 5 h |
| **2% (default)** | **7 min** | **5 h 43 min** | **5 h 50 min** |
| 5% | 15 min | 4 h 45 min | 5 h |
| 10% | 15 min | 2 h 15 min | 2 h 30 min |
| 50% | 15 min | 15 min | 30 min |

Example timeline at 2%:

```
start ─ 15 min you ─▶ 7 min dev ─▶ 5 h 43 min you ─▶ 7 min dev ─▶ 5 h 43 min you ─▶ …
```

The first slice is short, so even a short session contributes a little. Each IdleRig start
begins a new schedule.

### At least one share per dev slice

A dev slice only helps if the pool accepts at least one share. Pools tune the difficulty so that
even a slow CPU finds shares regularly, but at a 1–2% fee the slice is only a few minutes long.

So after the dev slice time has passed, IdleRig keeps mining for the developer until XMRig
reports one more accepted share, for **at most 20 minutes** in total. On a typical desktop the
first share arrives well within the normal slice, and this extension never kicks in.

If mining is paused during a dev slice (thread count `0`), no shares can be found. The slice then
ends at the 20-minute limit.

## Worker name

During dev slices the worker name is:

```
idlerig-<version>-<8 hex digits>
```

The hex digits are the first 8 characters of the SHA-256 hash of **your** wallet address. They
are the same for every IdleRig instance mining for the same wallet, and the address cannot be
recovered from them.

On the pool dashboard this tells the developer how many distinct users run IdleRig and which
versions. It reveals nothing else: no wallet, computer name or IP address is sent by IdleRig. The
pool sees your IP address, as it does for any pool connection.

## Where you can see it

- **Web UI → Dev fee card:**
  - who IdleRig is mining for right now;
  - countdown to the next switch, plus a progress bar during a dev slice;
  - fee and schedule;
  - dev pool, dev wallet (linked to the public dashboard) and dev worker name;
  - number of dev slices and dev shares in this session.
- **Tray icon:** amber during a dev slice.
- **Log:** the schedule at start-up and every switch, for example
  `Switched to pool.supportxmr.com:3333 wallet=87Qdre...c6oj worker=idlerig-0.3.0-1a2b3c4d via API`.

## Changing the fee

```powershell
IdleRig.exe --wallet <YOUR_WALLET> --donate-level 5     # be generous
IdleRig.exe --wallet <YOUR_WALLET> --donate-level 1     # minimum
```

The minimum is 1%. Lower values, including 0, are raised to 1% with a warning in the log.
