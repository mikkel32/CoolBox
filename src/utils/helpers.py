"""Various helper utilities."""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import subprocess
from typing import Literal, Dict, Any, Iterable, Callable
from pathlib import Path

from .cache import CacheManager
import psutil
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO)


def log(message: str) -> None:
    """Log a message using ``logging``."""
    logging.info(message)


def open_path(path: str) -> None:
    """Open *path* with the default application for the platform."""
    if platform.system() == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


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
    """Return a formatted multi-line string with system information."""
    mem = psutil.virtual_memory().total / (1024 * 1024 * 1024)
    info = (
        f"Platform: {platform.system()} {platform.release()}\n"
        f"Processor: {platform.processor()}\n"
        f"Architecture: {platform.architecture()[0]}\n"
        f"CPU Cores: {psutil.cpu_count(logical=True)}\n"
        f"Memory: {mem:.1f} GB\n"
        f"Python: {platform.python_version()}"
    )
    return info
