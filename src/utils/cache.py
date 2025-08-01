from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Generic, TypeVar, Iterable, Callable

from .file_manager import atomic_write
import json
import time
import threading

T = TypeVar("T")


@dataclass
class CacheItem(Generic[T]):
    """A single cache entry."""

    timestamp: float
    ttl: float
    value: T


class CacheManager(Generic[T]):
    """Thread-safe disk-backed cache with TTL support.

    The manager tracks the modification time of the backing file so
    updates written by other processes are picked up automatically. A
    lock guards internal state so the cache can be safely used from
    multiple threads.
    """

    def __init__(self, file: Path) -> None:
        self.file = file
        self._cache: Dict[str, CacheItem[T]] = self._load()
        self._mtime: float = self.file.stat().st_mtime if self.file.exists() else 0.0
        self.hits = 0
        self.misses = 0
        self._lock = threading.RLock()

    # -- persistence helpers -------------------------------------------------
    def _load(self) -> Dict[str, CacheItem[T]]:
        try:
            raw = json.loads(self.file.read_text())
        except Exception:
            return {}

        data: Dict[str, CacheItem[T]] = {}
        for k, v in raw.items():
            data[k] = CacheItem(
                float(v.get("timestamp", 0)),
                float(v.get("ttl", 0)),
                v.get("value"),
            )
        return data

    def _check_reload(self) -> None:
        """Reload the cache from disk if the file changed."""
        with self._lock:
            try:
                mtime = self.file.stat().st_mtime
            except FileNotFoundError:
                if self._cache:
                    self._cache.clear()
                self._mtime = 0.0
                return

            if mtime > self._mtime:
                self._cache = self._load()
                self._mtime = mtime

    def refresh(self) -> None:
        """Public method to reload the cache if the file changed."""
        self._check_reload()

    def _save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            k: {"timestamp": c.timestamp, "ttl": c.ttl, "value": c.value}
            for k, c in self._cache.items()
        }
        try:
            atomic_write(self.file, json.dumps(raw))
        except Exception:
            pass

    # -- public API ----------------------------------------------------------
    def get(self, key: str, ttl: float | None = None) -> T | None:
        """Return cached value for *key* or ``None`` if expired/missing."""
        self._check_reload()
        with self._lock:
            item = self._cache.get(key)
            if not item:
                self.misses += 1
                return None

            effective_ttl = item.ttl if ttl is None else min(item.ttl, ttl)
            if effective_ttl <= 0:
                return None

            if time.time() - item.timestamp < effective_ttl:
                self.hits += 1
                return item.value

            self._cache.pop(key, None)
            self._save()
            self.misses += 1
            return None

    def set(self, key: str, value: T, ttl: float) -> None:
        self._check_reload()
        with self._lock:
            self._cache[key] = CacheItem(time.time(), ttl, value)
            self._save()

    def clear(self) -> None:
        self._check_reload()
        with self._lock:
            self._cache.clear()
            try:
                self.file.unlink()
            except FileNotFoundError:
                pass
            self._mtime = 0.0
            self.hits = 0
            self.misses = 0

    def prune(self) -> None:
        self._check_reload()
        with self._lock:
            now = time.time()
            to_delete = [
                k
                for k, c in self._cache.items()
                if c.ttl > 0 and now - c.timestamp >= c.ttl
            ]
            for k in to_delete:
                self._cache.pop(k, None)
            if to_delete:
                self._save()

    def __len__(self) -> int:  # pragma: no cover - trivial
        self._check_reload()
        with self._lock:
            return len(self._cache)

    def stats(self) -> Dict[str, int]:  # pragma: no cover - simple
        """Return cache hit/miss statistics."""
        with self._lock:
            return {"hits": self.hits, "misses": self.misses}

    def reset_stats(self) -> None:
        """Reset hit/miss counters to zero."""
        with self._lock:
            self.hits = 0
            self.misses = 0

    def get_many(self, keys: Iterable[str], ttl: float | None = None) -> Dict[str, T]:
        """Return mapping of keys to cached values, dropping expired ones."""
        self._check_reload()
        now = time.time()
        results: Dict[str, T] = {}
        expired: list[str] = []
        with self._lock:
            for key in keys:
                item = self._cache.get(key)
                if not item:
                    self.misses += 1
                    continue
                effective_ttl = item.ttl if ttl is None else min(item.ttl, ttl)
                if effective_ttl > 0 and now - item.timestamp < effective_ttl:
                    results[key] = item.value
                    self.hits += 1
                else:
                    expired.append(key)
                    self.misses += 1
            for key in expired:
                self._cache.pop(key, None)
            if expired:
                self._save()
        return results

    def exists(self, key: str, ttl: float | None = None) -> bool:
        """Return ``True`` if *key* exists and is not expired."""
        return self.get(key, ttl) is not None

    def __contains__(self, key: str) -> bool:  # pragma: no cover - simple
        """Return ``True`` if *key* is present and not expired."""
        return self.exists(key)

    def get_or_set(self, key: str, default: Callable[[], T], ttl: float) -> T:
        """Return cached value for *key*, setting it via *default* if missing."""
        value = self.get(key, ttl)
        if value is not None:
            return value
        value = default()
        self.set(key, value, ttl)
        return value

    def delete(self, key: str) -> None:
        """Remove *key* from the cache if present."""
        self._check_reload()
        with self._lock:
            if key in self._cache:
                self._cache.pop(key, None)
                self._save()

    def pop(self, key: str, ttl: float | None = None) -> T | None:
        """Remove and return the cached value for *key* if present."""
        value = self.get(key, ttl)
        if value is not None:
            with self._lock:
                self._cache.pop(key, None)
                self._save()
        return value

    def keys(self, ttl: float | None = None) -> list[str]:
        """Return a list of valid keys, dropping expired ones."""
        data = self.get_many(list(self._cache.keys()), ttl)
        return list(data.keys())

    def values(self, ttl: float | None = None) -> list[T]:
        """Return a list of cached values, ignoring expired entries."""
        data = self.get_many(list(self._cache.keys()), ttl)
        return list(data.values())

    def items(self, ttl: float | None = None) -> list[tuple[str, T]]:
        """Return ``(key, value)`` pairs for valid entries."""
        data = self.get_many(list(self._cache.keys()), ttl)
        return list(data.items())

    def __iter__(self):  # pragma: no cover - simple
        """Iterate over valid keys."""
        return iter(self.keys())
