"""Developer hot reload controller for plugin workers."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping, MutableMapping


ReloadCallback = Callable[[str], None]


@dataclass(slots=True)
class _WatchState:
    paths: tuple[Path, ...]
    signatures: MutableMapping[Path, float]


class HotReloadController:
    """Poll watched paths and trigger reload callbacks on changes."""

    def __init__(self, *, interval: float = 1.0, callback: ReloadCallback | None = None) -> None:
        self._interval = max(0.2, interval)
        self._callback = callback
        self._watches: Dict[str, _WatchState] = {}
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def set_callback(self, callback: ReloadCallback) -> None:
        self._callback = callback

    def watch(self, plugin_id: str, paths: Iterable[Path]) -> None:
        with self._lock:
            normalised = tuple(sorted({path.resolve() for path in paths if path}))
            if not normalised:
                self._watches.pop(plugin_id, None)
                return
            signatures: MutableMapping[Path, float] = {}
            for path in normalised:
                signatures[path] = self._signature(path)
            self._watches[plugin_id] = _WatchState(paths=normalised, signatures=signatures)
        self._ensure_thread()

    def unwatch(self, plugin_id: str) -> None:
        with self._lock:
            self._watches.pop(plugin_id, None)
        if not self._watches:
            self.stop()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.0)
        self._thread = None
        self._stop.clear()

    def _ensure_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="coolbox-plugin-hotreload", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            time.sleep(self._interval)
            with self._lock:
                watches: Mapping[str, _WatchState] = dict(self._watches)
            for plugin_id, state in watches.items():
                if self._detect_changes(state):
                    callback = self._callback
                    if callback:
                        callback(plugin_id)

    def _detect_changes(self, state: _WatchState) -> bool:
        changed = False
        for path in state.paths:
            signature = self._signature(path)
            previous = state.signatures.get(path)
            if previous is None:
                state.signatures[path] = signature
                continue
            if signature != previous:
                state.signatures[path] = signature
                changed = True
        return changed

    @staticmethod
    def _signature(path: Path) -> float:
        try:
            if path.is_dir():
                return max((child.stat().st_mtime for child in path.glob("**/*")), default=path.stat().st_mtime)
            return path.stat().st_mtime
        except FileNotFoundError:
            return time.time()


__all__ = ["HotReloadController"]
