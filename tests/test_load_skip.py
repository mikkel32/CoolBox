from queue import Queue
import psutil

from src.utils.process_monitor import ProcessWatcher


def test_load_skip_params() -> None:
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = ProcessWatcher(q, load_threshold=50.0, load_cycles=3)
    try:
        assert watcher.load_threshold == 50.0
        assert watcher.load_cycles == 3
    finally:
        watcher.stop()


def test_should_pause_for_load(monkeypatch) -> None:
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = ProcessWatcher(q, load_threshold=10.0, load_cycles=2)
    called = []

    def fake_cpu_percent(interval=None):
        called.append(True)
        return 20.0

    monkeypatch.setattr(psutil, "cpu_percent", fake_cpu_percent)
    try:
        assert watcher._should_pause_for_load() is True
        # next call should use remaining skip cycle without calling cpu_percent
        called.clear()
        assert watcher._should_pause_for_load() is True
        assert not called
        # load below threshold ends skipping
        monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None: 1.0)
        assert watcher._should_pause_for_load() is False
    finally:
        watcher.stop()
