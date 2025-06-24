from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Generic, TypeVar
import json
import time

T = TypeVar("T")


@dataclass
class CacheItem(Generic[T]):
    """A single cache entry."""

    timestamp: float
    ttl: float
    value: T


class CacheManager(Generic[T]):
    """Simple disk-backed cache with TTL support.

    The manager tracks the modification time of the backing file so
    updates written by other processes are picked up automatically.
    """

    def __init__(self, file: Path) -> None:
        self.file = file
        self._cache: Dict[str, CacheItem[T]] = self._load()
        self._mtime: float = self.file.stat().st_mtime if self.file.exists() else 0.0
        self.hits = 0
        self.misses = 0

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
            self.file.write_text(json.dumps(raw))
        except Exception:
            pass

    # -- public API ----------------------------------------------------------
    def get(self, key: str, ttl: float | None = None) -> T | None:
        """Return cached value for *key* or ``None`` if expired/missing."""
        self._check_reload()
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
        self._cache[key] = CacheItem(time.time(), ttl, value)
        self._save()

    def clear(self) -> None:
        self._check_reload()
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
        now = time.time()
        to_delete = [k for k, c in self._cache.items() if c.ttl > 0 and now - c.timestamp >= c.ttl]
        for k in to_delete:
            self._cache.pop(k, None)
        if to_delete:
            self._save()

    def __len__(self) -> int:  # pragma: no cover - trivial
        self._check_reload()
        return len(self._cache)

    def stats(self) -> Dict[str, int]:  # pragma: no cover - simple
        """Return cache hit/miss statistics."""
        return {"hits": self.hits, "misses": self.misses}
