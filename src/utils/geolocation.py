from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import asyncio
import os
import threading
import queue
import requests

from .cache import CacheManager


@dataclass
class GeoInfo:
    """Geolocation details for an IP address."""

    ip: str
    city: str | None = None
    region: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None


_CACHE_FILE = Path(
    os.environ.get(
        "GEO_CACHE_FILE",
        str(Path.home() / ".coolbox" / "cache" / "geo_cache.json"),
    )
)
_CACHE_TTL = float(os.environ.get("GEO_CACHE_TTL", 86400))
GEO_CACHE: CacheManager[dict] = CacheManager(_CACHE_FILE)


_QUEUE: queue.Queue[tuple[str, Callable[[GeoInfo | None], None]]] | None = None
_WORKER: threading.Thread | None = None
_STOP = object()


def _ensure_worker() -> None:
    global _QUEUE, _WORKER
    if _WORKER is not None:
        return
    _QUEUE = queue.Queue()

    def worker() -> None:
        while True:
            item = _QUEUE.get()
            if item is _STOP:
                break
            ip, cb = item
            try:
                info = get_geo_info(ip)
            except Exception:
                info = None
            try:
                cb(info)
            finally:
                _QUEUE.task_done()

    _WORKER = threading.Thread(target=worker, daemon=True)
    _WORKER.start()


def shutdown_worker() -> None:
    global _QUEUE, _WORKER
    if _WORKER and _QUEUE:
        _QUEUE.put(_STOP)
        _WORKER.join(timeout=2)
    _WORKER = None
    _QUEUE = None


def queue_geo_lookup(ip: str, callback: Callable[[GeoInfo | None], None]) -> None:
    _ensure_worker()
    assert _QUEUE is not None
    _QUEUE.put((ip, callback))


def get_geo_info(ip: str) -> GeoInfo | None:
    GEO_CACHE.prune()
    cached = GEO_CACHE.get(ip, _CACHE_TTL)
    if cached is not None:
        return GeoInfo(
            ip,
            cached.get("city"),
            cached.get("region"),
            cached.get("country"),
            cached.get("lat"),
            cached.get("lon"),
        )

    sources = [
        f"https://ipapi.co/{ip}/json",
        f"https://ipwho.is/{ip}",
    ]
    for url in sources:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                continue
            data = resp.json()
        except Exception:
            continue

        city = data.get("city")
        region = data.get("region") or data.get("region_name")
        country = data.get("country_name") or data.get("country")
        lat = data.get("latitude") or data.get("lat")
        lon = data.get("longitude") or data.get("lon") or data.get("lng")

        GEO_CACHE.set(
            ip,
            {
                "city": city,
                "region": region,
                "country": country,
                "lat": lat,
                "lon": lon,
            },
            _CACHE_TTL,
        )
        return GeoInfo(ip, city, region, country, lat, lon)

    return None


async def async_get_geo_info(ip: str) -> GeoInfo | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, get_geo_info, ip)
