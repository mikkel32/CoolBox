from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable

import logging

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

try:  # pragma: no cover - runtime dependency check
    import psutil  # type: ignore
except ImportError:  # pragma: no cover
    from ..ensure_deps import ensure_psutil

    psutil = ensure_psutil()

console = Console()
plain_console = Console(no_color=True, force_terminal=False)


logger = logging.getLogger(__name__)


def get_system_info() -> str:
    """Return a concise multi-line system info string."""
    lines = [
        f"Python:   {sys.version.split()[0]} ({sys.executable})",
        f"Platform: {platform.system()} {platform.release()} ({platform.machine()})",
        f"Processor:{platform.processor() or 'unknown'}",
        f"Prefix:   {getattr(sys, 'prefix', '')}",
        f"TTY:      {console.is_terminal}",
    ]
    return "\n".join(lines)


def run_with_spinner(
    cmd: Iterable[str],
    *,
    message: str = "Working",
    timeout: float | None = None,
    capture_output: bool = False,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> str | None:
    """Run *cmd* while displaying a spinner and streaming output."""
    proc = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=cwd,
    )
    start = time.time()
    captured: list[str] = []

    if not console.is_terminal:
        # Plain fallback
        assert proc.stdout is not None
        for line in proc.stdout:
            logger.info(line.rstrip())
            if capture_output:
                captured.append(line)
            if timeout is not None and (time.time() - start) > timeout:
                proc.kill()
                raise subprocess.TimeoutExpired(proc.args, timeout)
        code = proc.wait(timeout=timeout)
        if code:
            raise subprocess.CalledProcessError(code, list(cmd))
        return "".join(captured) if capture_output else None

    with Progress(
        SpinnerColumn(style="bold blue"),
        TextColumn("{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task(message, start=True)
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                progress.console.print(line.rstrip())
                if capture_output:
                    captured.append(line)
                if timeout is not None and (time.time() - start) > timeout:
                    proc.kill()
                    raise subprocess.TimeoutExpired(proc.args, timeout)
            code = proc.wait(timeout=0.2 if timeout is None else max(0.2, timeout))
            if code:
                raise subprocess.CalledProcessError(code, list(cmd))
        finally:
            progress.update(task_id, completed=1)

    return "".join(captured) if capture_output else None


def open_path(path: str) -> None:
    """Open *path* with the default application for the platform."""
    if platform.system() == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


_SLUG_RE = re.compile(r"[^a-z0-9]+")
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def slugify(text: str, sep: str = "_") -> str:
    """Return *text* normalized for filenames or URLs."""
    text = text.lower()
    text = _SLUG_RE.sub(sep, text)
    return text.strip(sep)


def strip_ansi(text: str) -> str:
    """Return *text* without ANSI escape sequences."""
    return _ANSI_RE.sub("", text)


def get_system_metrics() -> Dict[str, Any]:
    """Return live system metrics for UI dashboards."""
    cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
    cpu = sum(cpu_per_core) / len(cpu_per_core) if cpu_per_core else 0.0
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    disk_io = psutil.disk_io_counters()
    freq = psutil.cpu_freq()
    per_core_freq: list[float] = []
    try:
        per_core_freq = [f.current for f in psutil.cpu_freq(percpu=True)]
    except Exception:
        pass
    temp: float | None = None
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for entries in temps.values():
                if entries:
                    temp = float(entries[0].current)
                    break
    except Exception:
        temp = None
    battery = None
    try:
        bat = psutil.sensors_battery()
        if bat is not None:
            battery = bat.percent
    except Exception:
        battery = None
    return {
        "cpu": cpu,
        "cpu_per_core": cpu_per_core,
        "memory": mem.percent,
        "memory_used": mem.used / (1024**3),
        "memory_total": mem.total / (1024**3),
        "disk": disk.percent,
        "disk_used": disk.used / (1024**3),
        "disk_total": disk.total / (1024**3),
        "sent": net.bytes_sent,
        "recv": net.bytes_recv,
        "read_bytes": disk_io.read_bytes,
        "write_bytes": disk_io.write_bytes,
        "cpu_freq": freq.current if freq else None,
        "cpu_freq_per_core": per_core_freq,
        "cpu_temp": temp,
        "battery": battery,
    }


__all__ = [
    "get_system_info",
    "run_with_spinner",
    "open_path",
    "slugify",
    "strip_ansi",
    "get_system_metrics",
    "console",
    "plain_console",
]
