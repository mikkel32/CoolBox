from __future__ import annotations

import threading
import time
from queue import Empty, SimpleQueue
from typing import Any, Dict


class ThreadManager:
    """Coordinate background threads for CoolBox.

    A process manager thread consumes commands from ``cmd_queue`` and a logger
    thread consumes log messages from ``log_queue``.  A monitor thread watches
    heartbeat timestamps to detect stalled threads which could indicate
    deadlocks or priority inversions during stress testing.
    """

    def __init__(self) -> None:
        self.log_queue: SimpleQueue[str] = SimpleQueue()
        self.cmd_queue: SimpleQueue[Any] = SimpleQueue()
        self.shutdown = threading.Event()
        self.lock = threading.Lock()
        self.heartbeats: Dict[str, float] = {}
        self.logs: list[str] = []

        self.logger_thread = threading.Thread(
            target=self._logger_loop, name="logger", daemon=True
        )
        self.process_thread = threading.Thread(
            target=self._process_loop, name="process_manager", daemon=True
        )
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop, name="thread_monitor", daemon=True
        )

    def start(self) -> None:
        """Start all background threads."""
        now = time.time()
        with self.lock:
            self.heartbeats = {"logger": now, "process": now}
        self.logger_thread.start()
        self.process_thread.start()
        self.monitor_thread.start()

    def stop(self) -> None:
        """Signal threads to stop and wait briefly for them."""
        self.shutdown.set()
        for t in (self.logger_thread, self.process_thread):
            t.join(timeout=1)

    def _logger_loop(self) -> None:
        while not self.shutdown.is_set():
            try:
                msg = self.log_queue.get(timeout=0.1)
            except Empty:
                pass
            else:
                self.logs.append(msg)
            with self.lock:
                self.heartbeats["logger"] = time.time()

    def _process_loop(self) -> None:
        while not self.shutdown.is_set():
            try:
                _task = self.cmd_queue.get(timeout=0.1)
            except Empty:
                pass
            else:
                time.sleep(0.01)
            with self.lock:
                self.heartbeats["process"] = time.time()

    def _monitor_loop(self) -> None:
        while not self.shutdown.is_set():
            if not self.lock.acquire(timeout=0.1):
                self.log_queue.put("heartbeat lock contention")
                time.sleep(0.5)
                continue
            try:
                now = time.time()
                for name, last in self.heartbeats.items():
                    if now - last > 1.0:
                        self.log_queue.put(f"{name} stalled")
            finally:
                self.lock.release()
            time.sleep(0.5)
