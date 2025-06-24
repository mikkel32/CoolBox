import sys
import subprocess
from src.utils import open_path, calc_hash, get_system_info


def test_calc_hash(tmp_path):
    file = tmp_path / "data.txt"
    file.write_text("hello")
    assert calc_hash(file) == "5d41402abc4b2a76b9719d911017c592"
    assert calc_hash(file, "sha1") == "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d"


def test_open_path(monkeypatch):
    called = {}

    def fake_startfile(path):
        called["cmd"] = ("startfile", path)

    def fake_popen(args):
        called["cmd"] = tuple(args)

        class P:
            def __init__(self):
                pass
        return P()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    if sys.platform.startswith("win"):
        monkeypatch.setattr("os.startfile", fake_startfile, raising=False)
        open_path("foo")
        assert called["cmd"] == ("startfile", "foo")
    elif sys.platform == "darwin":
        open_path("foo")
        assert called["cmd"] == ("open", "foo")
    else:
        open_path("foo")
        assert called["cmd"] == ("xdg-open", "foo")


def test_get_system_info():
    info = get_system_info()
    assert "Platform:" in info
    assert "Python:" in info
