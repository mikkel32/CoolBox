"""Helpers for working with the Windows console."""
from __future__ import annotations

import platform
import subprocess
from pathlib import Path

__all__ = [
    "hide_console",
    "hidden_creation_flags",
    "hide_terminal",
    "silence_stdio",
    "spawn_detached",
]


def hide_console(*, detach: bool = False) -> None:
    """Hide the current console window if running on Windows."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
            if detach:
                ctypes.windll.kernel32.FreeConsole()
    except Exception:
        # Best-effort; ignore any failure.
        pass


def hidden_creation_flags(*, detach: bool = True) -> int:
    """Return Windows-specific creation flags for a hidden process."""
    if platform.system() != "Windows":
        return 0
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if detach:
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return flags


def hide_terminal(*, detach: bool = True) -> None:
    """Hide the current terminal window cross-platform."""
    system = platform.system()
    if system == "Windows":
        hide_console(detach=detach)
        return
    if not detach:
        return
    try:
        import os

        if os.fork() > 0:
            os._exit(0)

        os.setsid()

        if os.fork() > 0:
            os._exit(0)

        os.umask(0)

        devnull = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            try:
                os.dup2(devnull, fd)
            except OSError:
                pass
    except Exception:
        # Best-effort; ignore failures on exotic platforms
        pass


def spawn_detached(args: list[str], *, use_pythonw: bool = True) -> None:
    """Launch a process fully detached and hidden from any console."""
    exe = Path(args[0])
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    system = platform.system()
    if system == "Windows":
        if use_pythonw and exe.name.lower() == "python.exe":
            pythonw = exe.with_name("pythonw.exe")
            if pythonw.is_file():
                exe = pythonw
        kwargs["creationflags"] = hidden_creation_flags()
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([str(exe), *map(str, args[1:])], **kwargs)


def silence_stdio() -> None:
    """Redirect ``sys.stdout`` and ``sys.stderr`` to ``os.devnull``."""
    import os
    import sys

    try:
        devnull = open(os.devnull, "w")
        sys.stdout = devnull  # type: ignore[assignment]
        sys.stderr = devnull  # type: ignore[assignment]
    except Exception:
        pass
