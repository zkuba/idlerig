"""IdleRig icon: a CPU chip with a crescent moon ("mining while you rest").

One drawing is used everywhere:

* the tray icon, with the background colour showing the state
* ``idlerig.ico`` for the .exe (``python -m idlerig.icon <out.ico>``, used by build.ps1)
* ``web/favicon.svg`` is the same design as a vector

Drawing is done at 4x size and downsampled, so small sizes stay smooth.
Requires Pillow.
"""

from __future__ import annotations

import sys

from PIL import Image, ImageDraw

STATE_COLOURS = {
    "user": (22, 160, 133),   # mining for you - teal
    "dev": (230, 162, 20),    # dev-fee slice - amber
    "off": (120, 132, 138),   # paused / stopped - grey
}
CHIP = (255, 255, 255, 255)
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def draw(size: int = 64, state: str = "user") -> Image.Image:
    s = size * 4
    u = s / 64  # design grid: 64 x 64
    bg = STATE_COLOURS.get(state, STATE_COLOURS["user"]) + (255,)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # rounded-square badge
    d.rounded_rectangle((2 * u, 2 * u, 62 * u, 62 * u), radius=14 * u, fill=bg)

    # chip pins: 3 per side, 2 at small sizes so they stay distinct
    for i in ((22, 32, 42) if size >= 32 else (25, 39)):
        for x0, y0, x1, y1 in (
            (i - 2.5, 10, i + 2.5, 17), (i - 2.5, 47, i + 2.5, 54),   # top / bottom
            (10, i - 2.5, 17, i + 2.5), (47, i - 2.5, 54, i + 2.5),   # left / right
        ):
            d.rounded_rectangle((x0 * u, y0 * u, x1 * u, y1 * u), radius=1.2 * u, fill=CHIP)

    # chip body
    d.rounded_rectangle((15 * u, 15 * u, 49 * u, 49 * u), radius=6 * u, fill=CHIP)

    # crescent moon cut into the chip
    d.ellipse((21 * u, 21 * u, 43 * u, 43 * u), fill=bg)
    d.ellipse((27 * u, 17 * u, 47 * u, 37 * u), fill=CHIP)

    return img.resize((size, size), Image.LANCZOS)


def save_ico(path: str) -> None:
    big = draw(256)
    big.save(path, format="ICO", sizes=[(n, n) for n in ICO_SIZES])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m idlerig.icon <output.ico|output.png>")
    out = sys.argv[1]
    if out.lower().endswith(".ico"):
        save_ico(out)
    else:
        draw(256).save(out)
    print(f"wrote {out}")
