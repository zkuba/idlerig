import pytest

from idlerig import cli


def parse(*argv):
    return cli.build_parser().parse_args(list(argv))


def test_defaults():
    a = parse("-u", "4" + "A" * 94)
    assert a.pool == cli.DEFAULT_POOL and a.donate_level == 2 and a.threads == cli.DEFAULT_THREADS
    assert a.away_after_min == 10 and not a.no_huge_pages


def test_help_renders(capsys):
    with pytest.raises(SystemExit):
        parse("--help")
    assert "--donate-level" in capsys.readouterr().out


def test_legacy_flags_are_accepted():
    a = parse("-u", "w", "--logout-after-min", "7", "--http-port-xmrig", "1234", "--tp", "60", "--http-debug")
    assert a.away_after_min == 7 and a.xmrig_http_port == 1234 and a.tp == 60


@pytest.mark.parametrize("wallet", ["YOUR_WALLET", "TWOJ_PORTFEL", ""])
def test_placeholder_wallet_is_rejected(wallet):
    p = cli.build_parser()
    with pytest.raises(SystemExit):
        cli.validate(p.parse_args(["-u", wallet]), p)


def test_bad_thread_spec_is_rejected():
    p = cli.build_parser()
    with pytest.raises(SystemExit):
        cli.validate(p.parse_args(["-u", "4" + "A" * 94, "-t", "lots"]), p)


def test_monero_address_pattern():
    assert cli.MONERO_ADDRESS.match("4" + "A" * 94)
    assert not cli.MONERO_ADDRESS.match("4" + "A" * 50)


def test_find_xmrig(tmp_path, monkeypatch):
    exe = tmp_path / "xmrig.exe"
    exe.write_bytes(b"")
    assert cli.find_xmrig(str(exe)) == exe
    assert cli.find_xmrig(str(tmp_path / "missing.exe")) is None
    monkeypatch.setattr(cli, "app_dir", lambda: tmp_path)
    assert cli.find_xmrig(None) == exe
