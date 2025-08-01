import json
import time

from src.utils.cache import CacheManager


def test_cache_refresh(tmp_path):
    file = tmp_path / "cache.json"
    cache = CacheManager[int](file)
    cache.set("a", 1, ttl=10)

    # Manually modify file without using cache object
    data = json.loads(file.read_text())
    data["b"] = {"timestamp": time.time(), "ttl": 10, "value": 2}
    file.write_text(json.dumps(data))

    # Refresh should load new entry
    cache.refresh()
    assert cache.get("b") == 2


def test_cache_prune_refresh(tmp_path):
    file = tmp_path / "cache.json"
    cache = CacheManager[int](file)
    cache.set("a", 1, ttl=0.1)
    time.sleep(0.2)
    cache.prune()
    assert len(cache) == 0


def test_cache_stats(tmp_path):
    file = tmp_path / "cache.json"
    cache = CacheManager[int](file)
    assert cache.stats() == {"hits": 0, "misses": 0}
    cache.set("a", 1, ttl=1)
    assert cache.get("a") == 1
    assert cache.get("b") is None
    stats = cache.stats()
    assert stats["hits"] == 1 and stats["misses"] == 1


def test_cache_get_many(tmp_path):
    file = tmp_path / "cache.json"
    cache = CacheManager[int](file)
    cache.set("a", 1, ttl=1)
    cache.set("b", 2, ttl=1)
    result = cache.get_many(["a", "b", "c"])
    assert result == {"a": 1, "b": 2}
    stats = cache.stats()
    assert stats["hits"] >= 2 and stats["misses"] >= 1


def test_cache_exists_and_get_or_set(tmp_path):
    file = tmp_path / "cache.json"
    cache = CacheManager[int](file)
    assert not cache.exists("a")

    def _default():
        return 42

    value = cache.get_or_set("a", _default, ttl=1)
    assert value == 42
    assert cache.exists("a")
    assert "a" in cache


def test_cache_delete(tmp_path):
    file = tmp_path / "cache.json"
    cache = CacheManager[int](file)
    cache.set("a", 1, ttl=10)
    cache.delete("a")
    assert not cache.exists("a")


def test_cache_pop(tmp_path):
    file = tmp_path / "cache.json"
    cache = CacheManager[int](file)
    cache.set("a", 1, ttl=10)
    val = cache.pop("a")
    assert val == 1
    assert not cache.exists("a")


def test_cache_reset_stats(tmp_path):
    file = tmp_path / "cache.json"
    cache = CacheManager[int](file)
    cache.set("a", 1, ttl=1)
    cache.get("a")
    cache.get("b")
    assert cache.stats() != {"hits": 0, "misses": 0}
    cache.reset_stats()
    assert cache.stats() == {"hits": 0, "misses": 0}


def test_cache_keys_values_items(tmp_path):
    file = tmp_path / "cache.json"
    cache = CacheManager[int](file)
    cache.set("a", 1, ttl=10)
    cache.set("b", 2, ttl=0.1)
    time.sleep(0.2)
    assert set(cache.keys()) == {"a"}
    assert list(cache) == ["a"]
    assert cache.values() == [1]
    assert cache.items() == [("a", 1)]
