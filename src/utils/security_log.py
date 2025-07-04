from __future__ import annotations

"""Simple JSON security event logger."""

from dataclasses import dataclass, asdict
import json
import time
import os
from pathlib import Path
from typing import List, Dict, AsyncGenerator
import asyncio

DEFAULT_LOG_PATH = Path.home() / ".coolbox" / "security_log.json"
MAX_EVENTS = int(os.environ.get("SECURITY_LOG_SIZE", 100))


@dataclass(slots=True)
class SecurityEvent:
    ts: float
    category: str
    message: str


def _load_raw(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def load_events(path: Path = DEFAULT_LOG_PATH) -> List[SecurityEvent]:
    """Return the list of security events from *path*."""
    raw = _load_raw(path)
    return [SecurityEvent(**e) for e in raw]


def _save(events: List[SecurityEvent], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(e) for e in events]
    path.write_text(json.dumps(data, indent=2))


def add_event(category: str, message: str, *, path: Path = DEFAULT_LOG_PATH) -> None:
    """Append a security event to the log."""
    events = load_events(path)
    events.append(SecurityEvent(time.time(), category, message))
    if len(events) > MAX_EVENTS:
        events = events[-MAX_EVENTS:]
    _save(events, path)


def clear_events(path: Path = DEFAULT_LOG_PATH) -> None:
    """Remove all security events from the log."""
    _save([], path)


def event_counts(path: Path = DEFAULT_LOG_PATH) -> Dict[str, int]:
    """Return a mapping of event category to count."""
    counts: Dict[str, int] = {}
    for event in load_events(path):
        counts[event.category] = counts.get(event.category, 0) + 1
    return counts


async def async_load_events(path: Path = DEFAULT_LOG_PATH) -> List[SecurityEvent]:
    """Asynchronously load events via :func:`load_events`."""
    return await asyncio.to_thread(load_events, path)


async def async_add_event(
    category: str, message: str, *, path: Path = DEFAULT_LOG_PATH
) -> None:
    """Asynchronous wrapper for :func:`add_event`."""
    await asyncio.to_thread(add_event, category, message, path=path)


async def async_clear_events(path: Path = DEFAULT_LOG_PATH) -> None:
    """Asynchronous wrapper for :func:`clear_events`."""
    await asyncio.to_thread(clear_events, path)


async def async_event_counts(path: Path = DEFAULT_LOG_PATH) -> Dict[str, int]:
    """Asynchronously compute event counts."""
    return await asyncio.to_thread(event_counts, path)


def tail_events(path: Path = DEFAULT_LOG_PATH, *, interval: float = 1.0):
    """Yield events appended to ``path`` after the generator starts."""
    last_count = len(load_events(path))
    try:
        while True:
            events = load_events(path)
            cur_count = len(events)
            if cur_count < last_count:
                last_count = cur_count
            elif cur_count > last_count:
                for event in events[last_count:]:
                    yield event
                last_count = cur_count
            time.sleep(interval)
    except GeneratorExit:
        return


def async_tail_events(
    path: Path = DEFAULT_LOG_PATH, *, interval: float = 1.0
) -> AsyncGenerator[SecurityEvent, None]:
    """Asynchronously yield newly appended events from ``path``."""
    # Compute the initial offset synchronously so events logged after this
    # function returns will be yielded.
    last_count = len(load_events(path))

    async def _gen() -> AsyncGenerator[SecurityEvent, None]:
        nonlocal last_count
        try:
            while True:
                events = await async_load_events(path)
                cur_count = len(events)
                if cur_count < last_count:
                    last_count = cur_count
                elif cur_count > last_count:
                    for event in events[last_count:]:
                        yield event
                    last_count = cur_count
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return

    return _gen()


# Backwards compatible aliases used by other modules
add_security_event = add_event
load_security_events = load_events
clear_security_events = clear_events
