from __future__ import annotations

"""Robust cross-platform process termination helpers."""

import os
import shutil
import time
from contextlib import contextmanager
try:
    import psutil
except ImportError:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_psutil

    psutil = ensure_psutil()
_psutil_process = psutil.Process
from .helpers import log
from .process_utils import run_command


def _taskkill(pid: int) -> None:
    run_command(["taskkill", "/F", "/T", "/PID", str(pid)], check=False)


def _kill_cmd(pid: int) -> None:
    if os.name != "nt":
        if os.getuid() != 0 and shutil.which("sudo"):
            run_command(["sudo", "-n", "kill", "-9", str(pid)], check=False)
        else:
            run_command(["kill", "-9", str(pid)], check=False)
    else:
        _taskkill(pid)


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


def kill_process(pid: int, *, timeout: float = 3.0) -> bool:
    """Forcefully terminate ``pid`` returning ``True`` if it exited."""
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
            _kill_cmd(p.pid)
            p.wait(timeout=timeout / 3)
            return True
        except Exception:
            return False

    attempts.append(hard)

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


def kill_process_tree(pid: int, *, timeout: float = 3.0) -> bool:
    """Kill ``pid`` and all of its children."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return False

    procs = parent.children(recursive=True)
    procs.append(parent)
    ok = True
    for p in procs:
        if not kill_process(p.pid, timeout=timeout):
            ok = False
    return ok
