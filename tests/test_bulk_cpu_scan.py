from queue import Queue
import os

from src.utils.process_monitor import ProcessEntry, ProcessWatcher


def test_scan_proc_stat_self() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
    watcher = ProcessWatcher(q)
    try:
        if not os.path.isdir("/proc"):
            return
        res = watcher._scan_proc_stat({os.getpid()})
        assert os.getpid() in res
        assert res[os.getpid()] > 0.0
    finally:
        watcher.stop()


def test_bulk_cpu_threshold_param() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
    watcher = ProcessWatcher(q, bulk_cpu_threshold=5, bulk_cpu_workers=2)
    try:
        assert watcher.bulk_cpu_threshold == 5
        assert watcher.bulk_cpu_workers == 2
    finally:
        watcher.stop()
