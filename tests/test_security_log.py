import asyncio
from threading import Thread
import pytest
from src.utils import security_log


def test_add_and_load(tmp_path, monkeypatch):
    path = tmp_path / "log.json"
    security_log.add_event("kill", "pid 1", path=path)
    events = security_log.load_events(path)
    assert len(events) == 1
    assert events[0].category == "kill"
    security_log.clear_events(path)
    assert security_log.load_events(path) == []


def test_event_counts(tmp_path):
    path = tmp_path / "log.json"
    for i in range(3):
        security_log.add_event("a", f"msg{i}", path=path)
    security_log.add_event("b", "msg", path=path)
    counts = security_log.event_counts(path)
    assert counts == {"a": 3, "b": 1}


def test_async_wrappers(tmp_path):
    path = tmp_path / "log.json"
    asyncio.run(security_log.async_add_event("x", "m", path=path))
    events = asyncio.run(security_log.async_load_events(path))
    assert len(events) == 1 and events[0].category == "x"
    counts = asyncio.run(security_log.async_event_counts(path))
    assert counts == {"x": 1}
    asyncio.run(security_log.async_clear_events(path))
    assert asyncio.run(security_log.async_load_events(path)) == []


def test_tail_events(tmp_path):
    path = tmp_path / "log.json"
    gen = security_log.tail_events(path=path, interval=0.01)
    Thread(target=security_log.add_event, args=("t", "msg"), kwargs={"path": path}).start()
    event = next(gen)
    assert event.category == "t"
    gen.close()


def test_tail_events_reset(tmp_path):
    path = tmp_path / "log.json"
    gen = security_log.tail_events(path=path, interval=0.01)
    Thread(target=security_log.add_event, args=("a", "1"), kwargs={"path": path}).start()
    evt1 = next(gen)
    assert evt1.category == "a"
    security_log.clear_events(path)
    Thread(target=security_log.add_event, args=("b", "2"), kwargs={"path": path}).start()
    evt = next(gen)
    assert evt.category == "b"
    gen.close()


@pytest.mark.asyncio
async def test_async_tail_events(tmp_path):
    path = tmp_path / "log.json"
    gen = security_log.async_tail_events(path=path, interval=0.01)
    await asyncio.to_thread(security_log.add_event, "at", "msg", path=path)
    event = await asyncio.wait_for(gen.__anext__(), 1)
    assert event.category == "at"
    await gen.aclose()


@pytest.mark.asyncio
async def test_async_tail_events_reset(tmp_path):
    path = tmp_path / "log.json"
    gen = security_log.async_tail_events(path=path, interval=0.01)
    await asyncio.to_thread(security_log.add_event, "aa", "1", path=path)
    event1 = await asyncio.wait_for(gen.__anext__(), 1)
    assert event1.category == "aa"
    await security_log.async_clear_events(path)
    await asyncio.to_thread(security_log.add_event, "bb", "2", path=path)
    event2 = await asyncio.wait_for(gen.__anext__(), 1)
    assert event2.category == "bb"
    await gen.aclose()
