from queue import Queue
from src.utils.process_monitor import ProcessEntry, ProcessWatcher


def test_process_watcher_reports_progress() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(q, batch_size=1)
    watcher.start()
    try:
        updates, removed, progress = q.get(timeout=5)
        assert 0.0 <= progress <= 1.0
    finally:
        watcher.stop()
        watcher.join(timeout=1)
