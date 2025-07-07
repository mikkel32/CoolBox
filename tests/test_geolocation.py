import asyncio
import threading
import sys
from pathlib import Path
import importlib.util
import types

import requests

src_dir = Path(__file__).resolve().parents[1] / "src" / "utils"
geo_path = src_dir / "geolocation.py"
utils_pkg = types.ModuleType("utils")
utils_pkg.__path__ = [str(src_dir)]
sys.modules.setdefault("utils", utils_pkg)
spec = importlib.util.spec_from_file_location("utils.geolocation", geo_path)
geo = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = geo
spec.loader.exec_module(geo)
async_get_geo_info = geo.async_get_geo_info
queue_geo_lookup = geo.queue_geo_lookup
shutdown_worker = geo.shutdown_worker
geo.GEO_CACHE.clear()


class DummyResp:
    status_code = 200

    def json(self):
        return {
            "city": "X",
            "region": "Y",
            "country_name": "Z",
            "latitude": 1.23,
            "longitude": 4.56,
        }


def fake_get(url, timeout=5):
    assert "1.2.3.4" in url
    return DummyResp()


def test_async_get_geo_info(monkeypatch):
    monkeypatch.setattr(requests, "get", fake_get)
    info = asyncio.run(async_get_geo_info("1.2.3.4"))
    assert info and info.city == "X" and info.country == "Z"
    assert info.latitude == 1.23 and info.longitude == 4.56


def test_queue_geo_lookup(monkeypatch):
    monkeypatch.setattr(requests, "get", fake_get)
    result: list[tuple[str, float, float]] = []
    evt = threading.Event()

    def cb(info):
        if info:
            result.append((info.city, info.latitude, info.longitude))
        evt.set()

    queue_geo_lookup("1.2.3.4", cb)
    assert evt.wait(1)
    shutdown_worker()
    assert result == [("X", 1.23, 4.56)]
