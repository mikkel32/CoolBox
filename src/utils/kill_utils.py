from __future__ import annotations

"""Robust cross-platform process termination helpers."""

import os
import subprocess
import shutil
from typing import Iterable

import psutil


def _run(cmd: Iterable[str]) -> bool:
    """Run *cmd* suppressing output. Return ``True`` if it executed."""
    try:
        subprocess.run(list(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return True
    except Exception:
        return False


def _taskkill(pid: int) -> None:
    _run(["taskkill", "/F", "/T", "/PID", str(pid)])


def _kill_cmd(pid: int) -> None:
    if os.name != "nt":
        if os.getuid() != 0 and shutil.which("sudo"):
            _run(["sudo", "-n", "kill", "-9", str(pid)])
        else:
            _run(["kill", "-9", str(pid)])
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
