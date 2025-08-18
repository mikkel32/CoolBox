from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Literal

from .cache import CacheManager


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
    """Return hash of ``path`` using *algo* with optional disk caching."""
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

    if cache is not None:
        cache.refresh()

    total = len(paths)
    completed = 0
    results: Dict[str, str] = {}

    def worker(p: str) -> tuple[str, str]:
        mtime = Path(p).stat().st_mtime
        key = f"{p}:{algo}"
        digest: str
        if cache is not None:
            entry = cache.get(key)
            if entry and abs(float(entry.get("mtime", 0.0)) - mtime) < 1e-6:
                return p, str(entry.get("digest", ""))
        digest = calc_hash(p, algo)
        if cache is not None:
            cache.set(key, {"mtime": mtime, "digest": digest}, ttl)
        return p, digest

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(worker, p): p for p in paths}
        for fut in as_completed(future_map):
            path, digest = fut.result()
            results[path] = digest
            completed += 1
            if progress is not None:
                progress(completed / total)

    if progress is not None:
        progress(None)
    return results

__all__ = [
    "calc_data_hash",
    "calc_hash",
    "calc_hash_cached",
    "calc_hashes",
]
