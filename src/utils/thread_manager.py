from __future__ import annotations

import threading
import time
import logging
from queue import Empty, SimpleQueue
from typing import Any, Dict, Callable


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
        # Queue of callables that need to execute on the Tk main thread.
        # Background threads enqueue functions here and ``ThreadManager``
        # schedules a custom Tk event so the main thread can drain the
        # queue without causing ``RuntimeError: main thread is not in main loop``
        # when ``after`` is called from worker threads.
        self._ui_queue: SimpleQueue[Callable[[], None]] = SimpleQueue()
        self._ui_window: Any | None = None
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

    def bind_window(self, window: Any) -> None:
        """Bind the manager to a Tk *window*.

        A custom virtual event ``<<ThreadManagerUI>>`` is installed so that
        callbacks enqueued by worker threads can be executed on the main
        thread without ever calling ``after`` from the wrong context.
        """

        self._ui_window = window
        window.bind("<<ThreadManagerUI>>", self._drain_ui_queue)

    # -- UI marshalling -------------------------------------------------
    def _enqueue_ui(self, func: Callable[[], None]) -> None:
        """Place *func* on the UI queue and trigger processing."""

        if self._ui_window is None:
            try:  # pragma: no cover - lightweight tests without UI
                func()
            except Exception:
                logging.getLogger(__name__).debug(
                    "failed to run UI callback", exc_info=True
                )
            return

        self._ui_queue.put(func)
        try:
            # ``event_generate`` is safe from background threads when
            # ``when='tail'`` so the event is appended to the queue and
            # processed by the main loop.
            self._ui_window.event_generate("<<ThreadManagerUI>>", when="tail")
        except Exception:  # pragma: no cover - best effort
            try:
                func()
            except Exception:
                logging.getLogger(__name__).debug(
                    "failed to run UI callback", exc_info=True
                )

    def _drain_ui_queue(self, _event: Any | None = None) -> None:
        while True:
            try:
                func = self._ui_queue.get_nowait()
            except Empty:
                break
            try:
                func()
            except Exception:  # pragma: no cover - best effort
                logging.getLogger(__name__).debug(
                    "UI callback raised", exc_info=True
                )

    def post_exception(self, window, exc: BaseException) -> None:
        """Report *exc* on the Tk main thread.

        The window's ``report_callback_exception`` hook is invoked so all
        dialogs and logging are handled by the global error handler.  This
        uses the internal UI queue so it is safe to call from background
        threads without triggering ``RuntimeError: main thread is not in main
        loop``.
        """
        tb = exc.__traceback__
        self._enqueue_ui(
            lambda exc=exc, tb=tb: window.report_callback_exception(
                type(exc), exc, tb
            )
        )

    def run_tool(
        self,
        name: str,
        func: callable,
        *,
        window,
        status_bar: Any | None = None,
    ) -> None:
        """Execute *func* in a daemon thread and surface exceptions.

        Any raised exception is logged with a full traceback and reported via
        ``status_bar`` and the application's global error handler.  Successful
        completion also emits a log and optional status message.  All UI interactions are
        marshalled back to the Tk main thread via ``window.after`` so failures
        never crash the Home view.
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
                        self._enqueue_ui(
                            lambda: status_bar.set_message(msg, "error")
                        )
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
                            self._enqueue_ui(
                                lambda: status_bar.set_message(
                                    f"{name} completed with warnings", "warning"
                                )
                            )
                        else:
                            self._enqueue_ui(
                                lambda: status_bar.set_message(
                                    f"{name} completed", "success"
                                )
                            )
            duration = time.time() - start
            self.log_queue.put(f"INFO:{name} finished in {duration:.2f}s")

        threading.Thread(target=runner, name=f"tool-{name}", daemon=True).start()

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
