"""Various helper utilities."""

from __future__ import annotations

import hashlib
import os
import platform
import re
import subprocess
from typing import Literal, Dict, Any, Iterable, Callable
from pathlib import Path

from .cache import CacheManager
import psutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

console = Console()


def log(message: str) -> None:
    """Log a message with rich formatting."""
    console.log(message)


def open_path(path: str) -> None:
    """Open *path* with the default application for the platform."""
    if platform.system() == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def run_with_spinner(
    cmd: Iterable[str], *, message: str = "Working", timeout: float | None = None,
    capture_output: bool = False, env: dict[str, str] | None = None,
    cwd: str | None = None
) -> str | None:
    """Run *cmd* while displaying an animated spinner and streaming output.

    If ``capture_output`` is ``True`` the process output is returned as a single
    string. Additional environment variables can be supplied via ``env``.
    The process can be run in a different directory using ``cwd``.
    """
    proc = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=cwd,
    )
    with Progress(
        SpinnerColumn(style="bold blue"),
        TextColumn("{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(message, start=True)
        assert proc.stdout is not None
        captured: list[str] = []
        for line in proc.stdout:
            progress.console.print(line.rstrip())
            if capture_output:
                captured.append(line)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise
        if code:
            raise subprocess.CalledProcessError(code, list(cmd))
    return "".join(captured) if capture_output else None


_SLUG_RE = re.compile(r"[^a-z0-9]+")
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def slugify(text: str, sep: str = "_") -> str:
    """Return *text* normalized for filenames or URLs.

    Parameters
    ----------
    sep:
        Character used to replace non-alphanumeric sequences.
    """
    text = text.lower()
    text = _SLUG_RE.sub(sep, text)
    return text.strip(sep)


def strip_ansi(text: str) -> str:
    """Return *text* without ANSI escape sequences."""
    return _ANSI_RE.sub("", text)


def calc_data_hash(
    data: bytes | str, algo: Literal["md5", "sha1", "sha256"] = "md5"
) -> str:
    """Return the hexadecimal hash of *data* using *algo*."""
    if isinstance(data, str):
        data = data.encode()
    hash_func = getattr(hashlib, algo)()
    hash_func.update(data)
    return hash_func.hexdigest()


def calc_hash(path: str, algo: Literal["md5", "sha1", "sha256"] = "md5") -> str:
    """Return the hexadecimal hash of ``path`` using *algo*."""
    hash_func = getattr(hashlib, algo)()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_func.update(chunk)
    return hash_func.hexdigest()


def calc_hash_cached(
    path: str,
    algo: Literal["md5", "sha1", "sha256"] = "md5",
    cache: CacheManager[Dict[str, Any]] | None = None,
    *,
    ttl: float = 365 * 24 * 60 * 60,
    refresh_cache: bool = True,
) -> str:
    """Return hash of ``path`` using *algo* with disk caching.

    Parameters
    ----------
    refresh_cache:
        If true, the cache will be reloaded from disk before reading.
        When computing many hashes concurrently the caller can disable
        this and refresh the cache once beforehand for better
        performance.
    """
    if cache is None:
        return calc_hash(path, algo)

    p = Path(path)
    key = f"{path}:{algo}"
    if refresh_cache:
        cache.refresh()
    entry = cache.get(key)
    mtime = p.stat().st_mtime
    if entry:
        stored_mtime = float(entry.get("mtime", 0.0))
        if abs(stored_mtime - mtime) < 1e-6:
            return str(entry.get("digest"))

    digest = calc_hash(path, algo)
    cache.set(key, {"mtime": mtime, "digest": digest}, ttl)
    return digest


def calc_hashes(
    paths: Iterable[str],
    algo: Literal["md5", "sha1", "sha256"] = "md5",
    cache: CacheManager[Dict[str, Any]] | None = None,
    *,
    workers: int | None = None,
    ttl: float = 365 * 24 * 60 * 60,
    progress: Callable[[float | None], None] | None = None,
) -> Dict[str, str]:
    """Return a mapping of path->digest for many files concurrently."""
    paths = list(paths)
    if not paths:
        if progress is not None:
            progress(None)
        return {}

    if workers is None:
        workers = min(32, os.cpu_count() or 1)

    total = len(paths)
    completed = 0
    results: Dict[str, str] = {}

    if cache is not None:
        cache.refresh()

    def update(value: float | None) -> None:
        if progress is not None:
            progress(value)

    cached: Dict[str, Any] = {}
    if cache is not None:
        keys = [f"{p}:{algo}" for p in paths]
        cached = cache.get_many(keys)

    def worker(path: str) -> tuple[str, str]:
        mtime = Path(path).stat().st_mtime
        key = f"{path}:{algo}"
        entry = cached.get(key)
        if entry and abs(float(entry.get("mtime", 0.0)) - mtime) < 1e-6:
            return path, str(entry.get("digest", ""))
        digest = calc_hash(path, algo)
        if cache is not None:
            cache.set(key, {"mtime": mtime, "digest": digest}, ttl)
        return path, digest

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(worker, p): p for p in paths}
        for fut in as_completed(future_map):
            path, digest = fut.result()
            results[path] = digest
            completed += 1
            update(completed / total)

    update(None)
    return results


def get_system_info() -> str:
    """Return a formatted multi-line string with detailed system information."""
    vm = psutil.virtual_memory()
    total_mem = vm.total / (1024**3)
    info_lines = [
        f"Platform: {platform.system()} {platform.release()}",
        f"Processor: {platform.processor()}",
        f"Architecture: {platform.architecture()[0]}",
        f"Physical Cores: {psutil.cpu_count(logical=False)}",
        f"Logical Cores: {psutil.cpu_count(logical=True)}",
        f"Total Memory: {total_mem:.1f} GB",
        f"Python: {platform.python_version()}",
    ]
    return "\n".join(info_lines)


def get_system_metrics() -> dict[str, Any]:
    """Return live system metrics for UI dashboards."""
    cpu = psutil.cpu_percent(interval=0.1)
    cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    disk_io = psutil.disk_io_counters()
    freq = psutil.cpu_freq()
    per_core_freq = []
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


def adjust_color(color: str, factor: float) -> str:
    """Return *color* adjusted by *factor*.

    ``factor`` may range from ``-1`` (black) to ``1`` (white). Positive values
    lighten the color while negative values darken it. The input may be in
    ``#rrggbb`` or ``#rgb`` form and the output is normalized to ``#rrggbb``.
    """

    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    if len(color) != 6:
        raise ValueError("invalid color format")

    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)

    factor = max(-1.0, min(1.0, factor))
    if factor >= 0:
        r = round(r + (255 - r) * factor)
        g = round(g + (255 - g) * factor)
        b = round(b + (255 - b) * factor)
    else:
        r = round(r * (1 + factor))
        g = round(g * (1 + factor))
        b = round(b * (1 + factor))

    return f"#{r:02x}{g:02x}{b:02x}"


def hex_brightness(color: str) -> float:
    """Return the perceptual brightness of *color* between 0 and 1."""

    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    if len(color) != 6:
        raise ValueError("invalid color format")

    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)

    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def lighten_color(color: str, factor: float) -> str:
    """Return *color* lightened by *factor* in the range ``0``-``1``."""

    return adjust_color(color, max(0.0, min(1.0, factor)))


def darken_color(color: str, factor: float) -> str:
    """Return *color* darkened by *factor* in the range ``0``-``1``."""

    return adjust_color(color, -max(0.0, min(1.0, factor)))
