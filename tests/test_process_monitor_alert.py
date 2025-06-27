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
