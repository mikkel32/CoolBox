import sys
import subprocess
from src.utils import open_path, calc_hash, calc_hashes, get_system_info
from src.utils.cache import CacheManager


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


def test_calc_hash_cached_and_bulk(tmp_path):
    files = [tmp_path / f"f{i}.txt" for i in range(3)]
    for i, f in enumerate(files):
        f.write_text(str(i))

    cache = CacheManager[dict](tmp_path / "cache.json")

    digests = calc_hashes([str(f) for f in files], cache=cache)
    assert len(digests) == 3

    hits_before = cache.stats()["hits"]
    digests2 = calc_hashes([str(f) for f in files], cache=cache)
    assert digests2 == digests
    assert cache.stats()["hits"] > hits_before
