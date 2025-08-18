import sys
import subprocess
from types import SimpleNamespace
from src.utils.system_utils import (
    open_path,
    get_system_info,
    get_system_metrics,
    run_with_spinner,
    slugify,
    strip_ansi,
)
from src.utils.hash_utils import (
    calc_hash,
    calc_hashes,
    calc_data_hash,
)
from src.utils.color_utils import (
    adjust_color,
    hex_brightness,
    lighten_color,
    darken_color,
)
from src.utils.cache import CacheManager
import io


def test_calc_hash(tmp_path):
    file = tmp_path / "data.txt"
    file.write_text("hello")
    assert calc_hash(file) == "5d41402abc4b2a76b9719d911017c592"
    assert calc_hash(file, "sha1") == "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d"


def test_calc_data_hash():
    assert calc_data_hash("hello") == "5d41402abc4b2a76b9719d911017c592"
    assert (
        calc_data_hash(b"hello", "sha1")
        == "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d"
    )


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


def test_get_system_metrics_non_blocking(monkeypatch):
    calls = []

    def fake_cpu_percent(interval=None, percpu=False):
        calls.append(interval)
        return [10.0, 20.0] if percpu else 15.0

    ns = SimpleNamespace
    gb = 1024 ** 3
    monkeypatch.setattr(
        get_system_metrics.__globals__["psutil"],
        "cpu_percent",
        fake_cpu_percent,
    )
    monkeypatch.setattr(
        get_system_metrics.__globals__["psutil"],
        "virtual_memory",
        lambda: ns(percent=50.0, used=2 * gb, total=4 * gb),
    )
    monkeypatch.setattr(
        get_system_metrics.__globals__["psutil"],
        "disk_usage",
        lambda _p: ns(percent=60.0, used=3 * gb, total=5 * gb),
    )
    monkeypatch.setattr(
        get_system_metrics.__globals__["psutil"],
        "net_io_counters",
        lambda: ns(bytes_sent=1, bytes_recv=2),
    )
    monkeypatch.setattr(
        get_system_metrics.__globals__["psutil"],
        "disk_io_counters",
        lambda: ns(read_bytes=3, write_bytes=4),
    )
    monkeypatch.setattr(
        get_system_metrics.__globals__["psutil"],
        "cpu_freq",
        lambda: ns(current=1000.0),
    )
    monkeypatch.setattr(
        get_system_metrics.__globals__["psutil"],
        "sensors_temperatures",
        lambda: {},
    )
    monkeypatch.setattr(
        get_system_metrics.__globals__["psutil"],
        "sensors_battery",
        lambda: ns(percent=88),
    )

    metrics = get_system_metrics()
    assert calls == [None]
    assert metrics["cpu"] == 15.0


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


def test_slugify():
    assert slugify("Hello World!") == "hello_world"
    assert slugify("foo-bar_baz") == "foo_bar_baz"
    assert slugify("Hello World!", sep="-") == "hello-world"


def test_strip_ansi():
    text = "\x1b[31mred\x1b[0m"
    assert strip_ansi(text) == "red"


def test_run_with_spinner(monkeypatch):
    """Ensure ``run_with_spinner`` streams output and checks return codes."""

    class DummyProc:
        def __init__(self):
            self.stdout = io.StringIO("hello\n")
            self.wait_called = False

        def wait(self, timeout=None):
            self.wait_called = timeout == 5
            return 0

    captured = {}

    last = {}

    def fake_popen(cmd, stdout=None, stderr=None, text=None, bufsize=None, env=None, cwd=None):
        proc = DummyProc()
        captured["cmd"] = cmd
        captured["env"] = env
        captured["cwd"] = cwd
        last["proc"] = proc
        return proc

    class DummyProgress:
        def __init__(self, *args, **kwargs):
            self.console = type("C", (), {"print": lambda self, *a, **k: None})()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            pass

        def add_task(self, *args, **kwargs):
            pass

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("src.utils.system_utils.Progress", DummyProgress)

    result = run_with_spinner(
        ["echo", "hi"], message="test", timeout=5, capture_output=True, env={"F": "1"}, cwd="/tmp"
    )
    assert captured["cmd"] == ["echo", "hi"]
    assert last["proc"].wait_called
    assert captured["env"] == {"F": "1"}
    assert captured["cwd"] == "/tmp"
    assert result == "hello\n"
