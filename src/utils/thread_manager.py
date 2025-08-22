from __future__ import annotations

import threading
import time
import logging
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

    def post_exception(self, window, exc: BaseException) -> None:
        """Report *exc* on the Tk main thread using ``window.after``.

        The window's ``report_callback_exception`` hook is invoked so all
        dialogs and logging are handled by the global error handler.
        If the window no longer exists or cannot schedule the callback,
        fall back to invoking the handler directly so errors are still
        surfaced.
        """
        tb = exc.__traceback__
        try:
            if threading.current_thread() is threading.main_thread():
                window.report_callback_exception(type(exc), exc, tb)
            else:  # schedule on main thread
                window.after(
                    0,
                    lambda exc=exc, tb=tb: window.report_callback_exception(
                        type(exc), exc, tb
                    ),
                )
        except Exception:  # pragma: no cover - best effort
            try:
                window.report_callback_exception(type(exc), exc, tb)
            except Exception:
                logging.getLogger(__name__).debug(
                    "failed to report exception", exc_info=True
                )

    def run_tool(
        self,
        name: str,
        func: callable,
        *,
        window,
        status_bar: Any | None = None,
        use_thread: bool = True,
    ) -> None:
        """Execute *func* and surface exceptions.

        Parameters
        ----------
        name:
            Friendly name for logging.
        func:
            Callable to execute.
        window:
            Tk root window for scheduling callbacks.
        status_bar:
            Optional status bar for user facing messages.
        use_thread:
            When ``True`` (the default) ``func`` runs in a background daemon
            thread.  If ``False`` the callable is executed on the Tk main
            thread via ``window.after`` which is required for any function that
            performs GUI operations.

        Any raised exception is logged with a full traceback and reported via
        ``status_bar`` and the application's global error handler.  Successful
        completion also emits a log and optional status message.  All UI
        interactions are marshalled back to the Tk main thread via
        ``window.after`` so failures never crash the Home view.
        """

        import traceback
        import warnings

        def runner() -> None:
            self.log_queue.put(f"INFO:Starting {name}")
            start = time.time()
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("default")
                try:
                    func()
                except Exception as exc:  # pragma: no cover - best effort
                    msg = f"{name} failed: {exc}"
                    self.log_queue.put(f"ERROR:{msg}")
                    for line in traceback.format_exc().splitlines():
                        self.log_queue.put(f"ERROR:{line}")
                    for warn in captured:
                        self.log_queue.put(
                            "WARNING:{category}:{filename}:{lineno}:{message}".format(
                                category=warn.category.__name__,
                                filename=warn.filename,
                                lineno=warn.lineno,
                                message=warn.message,
                            )
                        )
                    if status_bar is not None:
                        window.after(0, lambda: status_bar.set_message(msg, "error"))
                    self.post_exception(window, exc)
                else:
                    for warn in captured:
                        self.log_queue.put(
                            "WARNING:{category}:{filename}:{lineno}:{message}".format(
                                category=warn.category.__name__,
                                filename=warn.filename,
                                lineno=warn.lineno,
                                message=warn.message,
                            )
                        )
                    self.log_queue.put(f"INFO:{name} completed")
                    if status_bar is not None:
                        if captured:
                            window.after(
                                0,
                                lambda: status_bar.set_message(
                                    f"{name} completed with warnings", "warning"
                                ),
                            )
                        else:
                            window.after(
                                0,
                                lambda: status_bar.set_message(
                                    f"{name} completed", "success"
                                ),
                            )
            duration = time.time() - start
            self.log_queue.put(f"INFO:{name} finished in {duration:.2f}s")

        if use_thread:
            threading.Thread(target=runner, name=f"tool-{name}", daemon=True).start()
        else:
            window.after(0, runner)

    def _logger_loop(self) -> None:
        while not self.shutdown.is_set():
            try:
                msg = self.log_queue.get(timeout=0.1)
            except Empty:
                pass
            else:
                self.logs.append(msg)
                level_name, text = msg.split(":", 1) if ":" in msg else ("INFO", msg)
                level = getattr(logging, level_name.upper(), logging.INFO)
                logging.log(level, text)
            with self.lock:
                self.heartbeats["logger"] = time.time()

    def _process_loop(self) -> None:
        while not self.shutdown.is_set():
            try:
                _ = self.cmd_queue.get(timeout=0.1)
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
