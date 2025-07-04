from __future__ import annotations

"""Convenient wrappers for subprocess commands.

The :func:`run_command` helper executes an external command while hiding any
console window and optionally capturing its output.  It returns an empty string
on success or the captured output when ``capture`` is ``True``.  ``None`` is
returned when execution fails or, when ``check`` is ``True``, if the command
exits with a non-zero status.

The :func:`run_command_async` coroutine mirrors the synchronous helper for
``asyncio`` based workflows.

This module also exposes ``run_command_ex`` and ``run_command_async_ex`` which
provide the same behaviour but always return the process return code alongside
any captured output.  These helpers simplify tasks that need to inspect the
exit status without parsing exceptions.
"""

import subprocess
import asyncio
from typing import Sequence, Optional

from .win_console import hidden_creation_flags

__all__ = [
    "run_command",
    "run_command_async",
    "run_command_ex",
    "run_command_async_ex",
    "run_command_background",
]


def run_command(
    cmd: Sequence[str],
    *,
    capture: bool = False,
    timeout: float | None = 10.0,
    check: bool = True,
    creationflags: int | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> Optional[str]:
    """Execute *cmd* suppressing console windows.

    Parameters
    ----------
    cmd:
        Command and arguments to execute.
    capture:
        When ``True`` return the standard output as text.
    timeout:
        Maximum seconds to wait for the command. ``None`` disables the timeout.
    check:
        If ``True`` (default) a non-zero return code is treated as failure and
        ``None`` is returned.
    creationflags:
        Optional Windows creation flags for the new process. Defaults to flags
        that hide any console window.
    cwd:
        Optional working directory for the new process.
    env:
        Optional environment overrides for the new process.
    """
    if creationflags is None:
        creationflags = hidden_creation_flags(detach=False)

    kwargs = {
        "text": True,
        "stderr": subprocess.DEVNULL,
        "creationflags": creationflags,
        "cwd": cwd,
        "env": env,
    }
    try:
        if capture:
            return subprocess.check_output(list(cmd), timeout=timeout, **kwargs)

        subprocess.run(
            list(cmd),
            check=check,
            stdout=subprocess.DEVNULL,
            timeout=timeout,
            **kwargs,
        )

        return ""
    except Exception:
        return None


async def run_command_async(
    cmd: Sequence[str],
    *,
    capture: bool = False,
    timeout: float | None = 10.0,
    check: bool = True,
    creationflags: int | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> Optional[str]:
    """Asynchronously execute *cmd* hiding any console window.

    Parameters are identical to :func:`run_command`.
    """

    if creationflags is None:
        creationflags = hidden_creation_flags(detach=False)

    kwargs = {
        "stderr": asyncio.subprocess.DEVNULL,
        "creationflags": creationflags,
        "cwd": cwd,
        "env": env,
    }

    if capture:
        kwargs["stdout"] = asyncio.subprocess.PIPE
    else:
        kwargs["stdout"] = asyncio.subprocess.DEVNULL

    try:
        proc = await asyncio.create_subprocess_exec(*cmd, **kwargs)
        if timeout is not None:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        else:
            out, _ = await proc.communicate()
        if check and proc.returncode != 0:
            return None
        return out.decode() if capture else ""
    except Exception:
        return None


def run_command_ex(
    cmd: Sequence[str],
    *,
    capture: bool = False,
    timeout: float | None = 10.0,
    check: bool = True,
    creationflags: int | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[Optional[str], int | None]:
    """Execute ``cmd`` returning output and the exit status."""

    if creationflags is None:
        creationflags = hidden_creation_flags(detach=False)

    kwargs = {
        "text": True,
        "stderr": subprocess.DEVNULL,
        "creationflags": creationflags,
        "cwd": cwd,
        "env": env,
    }

    if capture:
        kwargs["stdout"] = subprocess.PIPE
    else:
        kwargs["stdout"] = subprocess.DEVNULL

    try:
        proc = subprocess.run(
            list(cmd),
            check=False,
            timeout=timeout,
            **kwargs,
        )
        if check and proc.returncode != 0:
            return None, proc.returncode
        return (proc.stdout if capture else ""), proc.returncode
    except Exception:
        return None, None


async def run_command_async_ex(
    cmd: Sequence[str],
    *,
    capture: bool = False,
    timeout: float | None = 10.0,
    check: bool = True,
    creationflags: int | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[Optional[str], int | None]:
    """Asynchronously execute ``cmd`` returning output and the exit status."""

    if creationflags is None:
        creationflags = hidden_creation_flags(detach=False)

    kwargs = {
        "stderr": asyncio.subprocess.DEVNULL,
        "creationflags": creationflags,
        "cwd": cwd,
        "env": env,
    }

    if capture:
        kwargs["stdout"] = asyncio.subprocess.PIPE
    else:
        kwargs["stdout"] = asyncio.subprocess.DEVNULL

    try:
        proc = await asyncio.create_subprocess_exec(*cmd, **kwargs)
        if timeout is not None:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        else:
            out, _ = await proc.communicate()
        if check and proc.returncode != 0:
            return None, proc.returncode
        return (out.decode() if capture else ""), proc.returncode
    except Exception:
        return None, None


def run_command_background(
    cmd: Sequence[str],
    *,
    creationflags: int | None = None,
    stdout: object | None = subprocess.DEVNULL,
    stderr: object | None = subprocess.DEVNULL,
    start_new_session: bool = False,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> bool:
    """Launch ``cmd`` detached from the current process.

    Parameters
    ----------
    start_new_session:
        When ``True`` the subprocess is started in a new session so it does not
        receive signals from the parent.
    cwd:
        Optional working directory for the new process.
    env:
        Optional environment overrides for the new process.
    """

    if creationflags is None:
        creationflags = hidden_creation_flags(detach=True)

    try:
        subprocess.Popen(
            list(cmd),
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            start_new_session=start_new_session,
            cwd=cwd,
            env=env,
        )
        return True
    except Exception:
        return False
