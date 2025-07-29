from __future__ import annotations

"""Robust cross-platform process termination helpers."""

import os
import shutil

try:
    import psutil
except ImportError:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_psutil

    psutil = ensure_psutil()
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

    for attempt in attempts:
        if attempt(proc):
            return True
        if not psutil.pid_exists(pid):
            return True
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
