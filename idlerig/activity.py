"""User activity detection (Windows).

Two signals are used to decide how hard the CPU may be used:

* seconds since the last keyboard/mouse input (``GetLastInputInfo``)
* whether the workstation is locked (``OpenDesktop`` + ``SwitchDesktop``)

On other platforms both functions return neutral values (0 s idle, not
locked), so IdleRig still runs but always stays in the ``active`` state.

Run ``python -m idlerig.activity`` for a live diagnostic.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LastInputInfo)]
    _user32.GetLastInputInfo.restype = wintypes.BOOL
    _kernel32.GetTickCount.argtypes = []
    _kernel32.GetTickCount.restype = wintypes.DWORD

    _user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _user32.OpenDesktopW.restype = wintypes.HANDLE
    _user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
    _user32.SwitchDesktop.restype = wintypes.BOOL
    _user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    _user32.CloseDesktop.restype = wintypes.BOOL

_DESKTOP_SWITCHDESKTOP = 0x0100


def idle_seconds() -> float:
    """Seconds since the last user input. Returns 0.0 when unavailable."""
    if not IS_WINDOWS:
        return 0.0
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(_LastInputInfo)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        raise OSError(ctypes.get_last_error(), "GetLastInputInfo failed")
    # Both values are 32-bit tick counts; masking handles the 49.7-day wrap-around.
    # (Mixing GetTickCount64 with the 32-bit dwTime would break after that.)
    elapsed_ms = (_kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return elapsed_ms / 1000.0


def is_locked() -> bool:
    """True when the interactive desktop is locked (or the secure desktop is shown).

    Returns False when detection is not possible, so a failure never makes
    IdleRig more aggressive than intended.
    """
    if not IS_WINDOWS:
        return False
    desktop = _user32.OpenDesktopW("Default", 0, False, _DESKTOP_SWITCHDESKTOP)
    if not desktop:
        return False
    try:
        return not _user32.SwitchDesktop(desktop)
    finally:
        _user32.CloseDesktop(desktop)


class SystemActivity:
    """Activity source backed by the OS. Tests substitute a fake with the same methods."""

    def idle_seconds(self) -> float:
        return idle_seconds()

    def is_locked(self) -> bool:
        return is_locked()


def _diagnose() -> None:
    print(f"Platform: {sys.platform}")
    if not IS_WINDOWS:
        print("Not Windows: idle time is always 0 and the session is never reported as locked.")
        return
    print("Press Ctrl+C to stop. Lock the screen (Win+L) to test lock detection.")
    try:
        while True:
            print(f"idle={idle_seconds():8.1f}s  locked={is_locked()}", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    _diagnose()
