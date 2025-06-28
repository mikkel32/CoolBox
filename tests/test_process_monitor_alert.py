from queue import Queue
from src.utils.process_monitor import ProcessWatcher


def test_process_watcher_alert_defaults():
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = ProcessWatcher(q)
    assert watcher.cpu_alert == 80.0
    assert watcher.mem_alert == 500.0
    watcher.stop()


def test_process_watcher_alert_custom():
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = ProcessWatcher(q, cpu_alert=70.0, mem_alert=400.0)
    assert watcher.cpu_alert == 70.0
    assert watcher.mem_alert == 400.0
    watcher.stop()


def test_process_watcher_batch_size():
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = ProcessWatcher(q, batch_size=25)
    try:
        assert watcher.batch_size == 25
    finally:
        watcher.stop()


class _Obj:
    pass


def test_next_batch(monkeypatch):
    objs = [_Obj() for _ in range(5)]

    def fake_pids():
        return list(range(5))

    def fake_iter(attrs=None):  # type: ignore[unused-argument]
        for o in objs:
            yield o

    monkeypatch.setattr("psutil.pids", fake_pids)
    monkeypatch.setattr("psutil.process_iter", fake_iter)

    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = ProcessWatcher(q, batch_size=3)
    try:
        batch, end = watcher._next_batch([])
        assert batch == objs[:3]
        assert end is False
        batch, end = watcher._next_batch([])
        assert batch == objs[3:]
        assert end is True
    finally:
        watcher.stop()


def test_update_batch_size():
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = ProcessWatcher(q, batch_size=50, auto_batch=True, min_batch_size=20, max_batch_size=100)
    try:
        watcher._cycle_elapsed = watcher.target_interval * 2
        watcher._update_batch_size()
        assert watcher.batch_size < 50
        prev = watcher.batch_size
        watcher._cycle_elapsed = watcher.target_interval * 0.5
        watcher._update_batch_size()
        assert watcher.batch_size > prev
    finally:
        watcher.stop()


def test_update_batch_size_activity():
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = ProcessWatcher(q, batch_size=50, auto_batch=True, min_batch_size=20, max_batch_size=100)
    try:
        watcher.process_count = 10
        watcher._cycle_elapsed = watcher.target_interval * 0.5
        watcher._cycle_updates = 8
        watcher._cycle_trending = 5
        watcher._update_batch_size()
        assert watcher.batch_size < 50
    finally:
        watcher.stop()


def test_finish_cycle_metrics():
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = ProcessWatcher(q, batch_size=50)
    try:
        watcher.process_count = 10
        watcher._cycle_updates = 4
        watcher._cycle_trending = 2
        watcher._finish_cycle()
        assert watcher.recent_change_ratio == 0.4
        assert watcher.recent_trend_ratio == 0.2
    finally:
        watcher.stop()


def test_average_metrics():
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = ProcessWatcher(q, batch_size=40)
    try:
        watcher.process_count = 10
        watcher._cycle_updates = 2
        watcher._cycle_trending = 1
        watcher._cycle_elapsed = watcher.target_interval * 0.8
        watcher._finish_cycle()
        watcher._cycle_updates = 2
        watcher._cycle_trending = 1
        watcher._cycle_elapsed = watcher.target_interval * 0.9
        watcher._finish_cycle()
        assert watcher.average_batch_size == watcher.batch_size
        assert watcher.average_cycle_time > 0
    finally:
        watcher.stop()


def test_interval_bounds():
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = ProcessWatcher(q, interval=5.0, min_interval=1.0, max_interval=3.0)
    try:
        assert watcher.interval == 3.0
        watcher.interval = 0.2
        watcher._finish_cycle()
        assert watcher.interval == 1.0
    finally:
        watcher.stop()


def test_average_interval():
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = ProcessWatcher(q, interval=1.5)
    try:
        watcher._cycle_elapsed = 0.1
        watcher._finish_cycle()
        watcher.interval = 2.0
        watcher._cycle_elapsed = 0.2
        watcher._finish_cycle()
        assert watcher.average_interval >= 1.5
    finally:
        watcher.stop()


def test_auto_interval_env(monkeypatch):
    monkeypatch.setenv("FORCE_QUIT_AUTO_INTERVAL", "0")
    import importlib
    import src.utils.process_monitor as pm
    importlib.reload(pm)
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = pm.ProcessWatcher(q)
    try:
        assert watcher.adaptive is False
    finally:
        watcher.stop()


def test_resize_executor(monkeypatch):
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = ProcessWatcher(q, max_workers=2, min_workers=2, max_worker_limit=8)
    try:
        watcher.process_count = 20
        watcher._maybe_resize_executor()
        assert watcher.worker_count > 2
        prev = watcher.worker_count
        watcher.process_count = 1
        watcher._maybe_resize_executor()
        assert watcher.worker_count <= prev
        assert watcher.worker_count >= 2
    finally:
        watcher.stop()


def test_min_workers_env(monkeypatch):
    monkeypatch.setenv("FORCE_QUIT_MIN_WORKERS", "3")
    import importlib
    import src.utils.process_monitor as pm
    importlib.reload(pm)
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = pm.ProcessWatcher(q)
    try:
        assert watcher.min_workers == 3
    finally:
        watcher.stop()


def test_ignore_names_check():
    q: Queue[tuple[dict[int, object], set[int]]] = Queue()
    watcher = ProcessWatcher(q, ignore_names={"bash"})
    try:
        assert watcher._should_ignore_process("bash") is True
        assert watcher._should_ignore_process("python") is False
    finally:
        watcher.stop()
