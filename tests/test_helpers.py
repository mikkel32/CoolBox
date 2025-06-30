import sys
import subprocess
from src.utils import (
    open_path,
    calc_hash,
    calc_hashes,
    get_system_info,
    get_system_metrics,
)
from src.utils.cache import CacheManager
from src.utils.helpers import adjust_color, hex_brightness, lighten_color
from src.utils.helpers import darken_color


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


def test_get_system_metrics():
    metrics = get_system_metrics()
    assert "cpu" in metrics
    assert "memory" in metrics
    assert "disk" in metrics
    assert "cpu_per_core" in metrics
    assert "cpu_freq" in metrics
    assert "cpu_temp" in metrics
    assert "battery" in metrics
    assert "read_bytes" in metrics
    assert "write_bytes" in metrics


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


def test_lighten_color() -> None:
    assert lighten_color("#000000", 0) == "#000000"
    assert lighten_color("#ffffff", 0) == "#ffffff"
    assert lighten_color("#000000", 1) == "#ffffff"
    mid = lighten_color("#000000", 0.5)
    assert mid.lower() in {"#7f7f7f", "#808080"}


def test_darken_color() -> None:
    assert darken_color("#ffffff", 0) == "#ffffff"
    assert darken_color("#000000", 0) == "#000000"
    assert darken_color("#ffffff", 1) == "#000000"
    mid = darken_color("#ffffff", 0.5)
    assert mid.lower() in {"#7f7f7f", "#808080"}


def test_adjust_color_and_brightness() -> None:
    assert adjust_color("#000", 0.5).lower() in {"#7f7f7f", "#808080"}
    assert adjust_color("#fff", -0.5).lower() in {"#7f7f7f", "#808080"}
    assert hex_brightness("#000") == 0
    assert hex_brightness("#fff") == 1
