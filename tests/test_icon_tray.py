import pytest

PIL = pytest.importorskip("PIL")

from idlerig.icon import ICO_SIZES, STATE_COLOURS, draw, save_ico  # noqa: E402


@pytest.mark.parametrize("state", list(STATE_COLOURS))
@pytest.mark.parametrize("size", [16, 32, 64])
def test_draw_sizes_and_colours(size, state):
    img = draw(size, state)
    assert img.size == (size, size) and img.mode == "RGBA"
    assert img.getpixel((0, 0))[3] < 16  # (nearly) transparent corner; resampling may leave a trace
    if size < 32:
        return  # too few pixels for a meaningful colour check
    # The most common non-white opaque colour is the state colour.
    counts = img.getcolors(size * size)
    colours = [c for n, c in sorted(counts, reverse=True) if c[3] == 255 and c[:3] != (255, 255, 255)]
    assert colours[0][:3] == pytest.approx(STATE_COLOURS[state], abs=20)


def test_ico_contains_all_sizes(tmp_path):
    from PIL import Image

    path = tmp_path / "idlerig.ico"
    save_ico(str(path))
    with Image.open(path) as ico:
        assert set(ico.info["sizes"]) == {(n, n) for n in ICO_SIZES}


def test_tray_status_text():
    pytest.importorskip("pystray")
    from idlerig.tray import Tray

    class Miner:
        paused = False
        threads = 4
        running = True

        def is_running(self):
            return self.running

        def summary(self):
            return {"hashrate": {"total": [2150.0, None, None]}}

    class Services:
        miner = Miner()
        governor = type("G", (), {"state": "idle"})()
        rotator = type("R", (), {"owner": "user"})()

    t = Tray(Services(), "http://127.0.0.1/", on_exit=lambda: None)
    assert t.status_text() == "Mining for you - idle, 4 threads, 2.15 kH/s"
    Services.rotator.owner = "dev"
    assert t._key() == "dev" and t.status_text().startswith("Dev-fee slice")
    Services.miner.running = False
    assert t._key() == "off" and t.status_text() == "Stopped (idle)"
