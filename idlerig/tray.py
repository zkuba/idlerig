"""Optional system-tray icon (needs ``pystray`` and ``Pillow``).

IdleRig lives in the notification area. The icon colour shows the state:
teal = mining for you, amber = dev-fee slice, grey = paused or stopped.
The menu's first line shows the current status; double-click (or "Open web UI")
opens the dashboard.
"""

from __future__ import annotations

import logging
import threading
import webbrowser
from typing import Callable

from idlerig import __app_name__, __version__
from idlerig.web import Services

log = logging.getLogger(__name__)

try:
    import pystray

    from idlerig.icon import draw
except ImportError:  # pragma: no cover - optional dependency
    pystray = None


def available() -> bool:
    return pystray is not None


def _fmt_hashrate(h) -> str:
    if h is None:
        return "-"
    return f"{h / 1000:.2f} kH/s" if h >= 1000 else f"{h:.0f} H/s"


class Tray:
    def __init__(self, services: Services, ui_url: str, on_exit: Callable[[], None]):
        self.services = services
        self.ui_url = ui_url
        self.on_exit = on_exit
        self.icon = None
        self._images = {k: draw(64, k) for k in ("user", "dev", "off")}

    def _key(self) -> str:
        m = self.services.miner
        if not m.is_running() or m.paused:
            return "off"
        return "dev" if self.services.rotator.owner == "dev" else "user"

    def status_text(self) -> str:
        m = self.services.miner
        state = self.services.governor.state or "starting"
        key = self._key()
        if key == "off":
            what = "Paused" if m.paused else "Stopped"
            return f"{what} ({state})"
        owner = "Dev-fee slice" if key == "dev" else "Mining for you"
        hashrate = _fmt_hashrate(self._hashrate())
        return f"{owner} - {state}, {m.threads} threads, {hashrate}"

    def _hashrate(self):
        from idlerig.xmrig import summary_hashrate
        return summary_hashrate(self.services.miner.summary())

    def refresh(self) -> None:
        """Update icon, tooltip and menu; safe to call from any thread."""
        if self.icon is None:
            return
        self.icon.icon = self._images[self._key()]
        # Windows limits tooltips to 127 characters.
        self.icon.title = f"{__app_name__} {__version__}\n{self.status_text()}"[:127]
        self.icon.update_menu()

    def run(self) -> None:
        """Blocks; run in its own thread."""
        m = self.services.miner

        def in_background(fn):
            return lambda: threading.Thread(target=fn, daemon=True).start()

        menu = pystray.Menu(
            pystray.MenuItem(lambda _: self.status_text(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open web UI", lambda: webbrowser.open(self.ui_url), default=True),
            pystray.MenuItem("Start mining", in_background(lambda: m.start(source="tray")),
                             visible=lambda _: not m.is_running()),
            pystray.MenuItem("Stop mining", in_background(lambda: m.stop(source="tray")),
                             visible=lambda _: m.is_running()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"Exit {__app_name__}", self._exit),
        )
        self.icon = pystray.Icon("idlerig", self._images[self._key()], __app_name__, menu)
        self.refresh()
        self.icon.run()

    def _exit(self) -> None:
        log.info("Exit requested from the tray")
        self.on_exit()

    def stop(self) -> None:
        if self.icon is not None:
            self.icon.stop()
