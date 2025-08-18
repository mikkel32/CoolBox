from __future__ import annotations

"""Robust cross-platform process termination helpers."""

import logging
import os
import signal
import time
from contextlib import contextmanager
from threading import Event, Thread
from typing import Callable

try:
    import psutil
except ImportError:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_psutil

    psutil = ensure_psutil()

_psutil_process = psutil.Process
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeElapsedColumn,
)
from .system_utils import console


logger = logging.getLogger(__name__)


def log(message: str) -> None:
    """Backward compatible log function."""
    logger.info(message)


def _kill_cmd(pid: int) -> bool:
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_TERMINATE = 0x0001
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if not handle:
                return False
            try:
                if kernel32.TerminateProcess(handle, 1) == 0:
                    return False
            finally:
                kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except Exception:
        return False


@contextmanager
def _priority_boost() -> None:
    """Temporarily boost the current thread priority."""
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            proc_handle = kernel32.GetCurrentProcess()
            thread_handle = kernel32.GetCurrentThread()
            REALTIME_PRIORITY_CLASS = 0x00000100
            THREAD_PRIORITY_TIME_CRITICAL = 15
            prev_class = kernel32.GetPriorityClass(proc_handle)
            prev_thread = kernel32.GetThreadPriority(thread_handle)
            kernel32.SetPriorityClass(proc_handle, REALTIME_PRIORITY_CLASS)
            kernel32.SetThreadPriority(thread_handle, THREAD_PRIORITY_TIME_CRITICAL)
            yield
        finally:
            try:
                kernel32.SetPriorityClass(proc_handle, prev_class)
                kernel32.SetThreadPriority(thread_handle, prev_thread)
            except Exception:
                pass
    else:
        proc_class = _psutil_process if psutil.Process is _psutil_process else None
        if proc_class is None:
            yield
            return
        proc = proc_class(os.getpid())
        try:
            prev_nice = proc.nice()
        except Exception:
            prev_nice = None
        try:
            if prev_nice is not None:
                try:
                    proc.nice(-20)
                except Exception:
                    pass
            yield
        finally:
            if prev_nice is not None:
                try:
                    proc.nice(prev_nice)
                except Exception:
                    pass


def _spinner(duration: float, done: Event) -> None:
    """Display a spinner/progress bar for ``duration`` seconds."""
    with Progress(
        SpinnerColumn(style="bold blue"),
        BarColumn(bar_width=None),
        TextColumn("Killing"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("kill", total=duration)
        start = time.perf_counter()
        while not done.is_set():
            elapsed = time.perf_counter() - start
            progress.update(task, completed=min(elapsed, duration))
            if elapsed >= duration:
                break
            time.sleep(0.1)


def kill_process(
    pid: int,
    *,
    timeout: float = 3.0,
    watchdog: float | None = None,
    on_timeout: Callable[[], bool] | None = None,
) -> bool:
    """Forcefully terminate ``pid`` returning ``True`` if it exited.

    Parameters
    ----------
    watchdog:
        If set, show a spinner for ``watchdog`` seconds and prompt for
        cancellation if the kill exceeds this duration.
    on_timeout:
        Optional callback invoked when the watchdog elapses. It should
        return ``True`` to continue waiting or ``False`` to cancel.
    """
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return False

    attempts = []

    def term(p: psutil.Process) -> bool:
        try:
            p.terminate()
            p.wait(timeout=timeout / 3)
            return True
        except Exception:
            return False

    attempts.append(term)

    def kill(p: psutil.Process) -> bool:
        try:
            p.kill()
            p.wait(timeout=timeout / 3)
            return True
        except Exception:
            return False

    attempts.append(kill)

    def hard(p: psutil.Process) -> bool:
        try:
            if not _kill_cmd(p.pid):
                return False
            p.wait(timeout=timeout / 3)
            return True
        except Exception:
            return False

    attempts.append(hard)

    spinner_done = Event()
    if watchdog is not None:
        thread = Thread(target=_spinner, args=(watchdog, spinner_done), daemon=True)
        thread.start()
    else:
        thread = None

    start = time.perf_counter()
    psutil.cpu_percent(None)
    with _priority_boost():
        for attempt in attempts:
            if attempt(proc):
                break
            if not psutil.pid_exists(pid):
                break
            if psutil.cpu_percent(None) > 90:
                break
    elapsed = time.perf_counter() - start
    if thread is not None:
        spinner_done.set()
        thread.join()
        if elapsed > watchdog:
            proceed = True
            if on_timeout is not None:
                proceed = on_timeout()
            else:
                try:
                    resp = console.input("Kill taking too long. Cancel? [y/N]: ")
                    proceed = not resp.strip().lower().startswith("y")
                except Exception:
                    proceed = True
            if not proceed:
                log(f"kill_process({pid}) canceled after {elapsed:.3f}s")
                return False
            log(f"kill_process({pid}) exceeded watchdog {watchdog:.3f}s")
    log(f"kill_process({pid}) latency {elapsed:.3f}s")
    if psutil.pid_exists(pid):
        try:
            status = psutil.Process(pid).status()
            return status in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}
        except psutil.NoSuchProcess:
            return True
        except Exception:
            return False
    return True


def kill_process_tree(
    pid: int,
    *,
    timeout: float = 3.0,
    watchdog: float | None = None,
    on_timeout: Callable[[], bool] | None = None,
) -> bool:
    """Kill ``pid`` and all of its children."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return False

    procs = parent.children(recursive=True)
    procs.append(parent)
    ok = True
    start = time.perf_counter()
    for p in procs:
        if not kill_process(
            p.pid,
            timeout=timeout,
            watchdog=watchdog,
            on_timeout=on_timeout,
        ):
            ok = False
    elapsed = time.perf_counter() - start
    log(f"kill_process_tree({pid}) latency {elapsed:.3f}s")
    return ok
