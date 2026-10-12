# Contributing

Thanks for helping with IdleRig.

1. Read [docs/how-it-works.md](docs/how-it-works.md) and [docs/building.md](docs/building.md).
2. Create a branch, make your change, and add or update tests in `tests/`.
3. Run `.venv\Scripts\python -m pytest -q` and make sure everything passes.
4. If the change is user-visible, update the relevant page in `docs/` and add a line to
   `CHANGELOG.md` under the unreleased version.
5. Open a pull request describing what changed and why.

Guidelines:

- **English everywhere:** code, comments, logs, UI, docs.
- **Dependencies.** Keep `idlerig/` to the Python standard library; the tray is the only optional
  exception.
- **Never hide what IdleRig does.** Every dev-fee or pool switch must be visible in the log and the
  web UI.
- **Bugs.** Include `logs/idlerig.log` (remove your wallet if you like), your XMRig version and
  your command line.
