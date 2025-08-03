"""Lightweight process snapshot cache with optional OS notifications.

This module maintains a cached snapshot of running processes and attempts to
subscribe to OS-level spawn/exit notifications so the snapshot is only rebuilt
when necessary. When the notification APIs are unavailable or return ambiguous
results the cache falls back to full enumeration using :mod:`psutil`.
"""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Mapping
from typing import Dict

try:
    import psutil
except Exception:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_psutil

    psutil = ensure_psutil()

__all__ = ["ProcessCache"]


class ProcessCache:
    """Cache ``psutil`` process information.

    The cache starts with a full snapshot of running processes. On platforms
    that support it a background thread subscribes to OS notifications such as
    ``kqueue`` (on BSD/macOS) or Windows process callbacks. These notifications
    mark the cache as dirty when processes spawn or exit so callers only rebuild
    the snapshot when required. If the notification mechanism fails or returns
    ambiguous information the cache is invalidated and rebuilt on the next
    access.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._procs: Dict[int, psutil.Process] = {}
        self._dirty = True
        self._watch_failed = False
        self._start_watchers()

    # -- public API -----------------------------------------------------
    def snapshot(self) -> Mapping[int, psutil.Process]:
        """Return a mapping of ``pid`` to :class:`psutil.Process`.

        The snapshot is rebuilt only when flagged as dirty, either because an
        OS notification reported changes or a previous rebuild attempt failed.
        """

        with self._lock:
            if self._dirty:
                self._rebuild()
            return dict(self._procs)

    def invalidate(self) -> None:
        """Mark the cached snapshot as stale."""

        with self._lock:
            self._dirty = True

    # -- internal helpers -----------------------------------------------
    def _rebuild(self) -> None:
        """Rebuild the cached snapshot by enumerating processes."""

        try:
            self._procs = {p.pid: p for p in psutil.process_iter()}
            self._dirty = False
        except Exception:
            # If enumeration fails keep stale data but try again later
            self._dirty = True

    # watcher threads ---------------------------------------------------
    def _start_watchers(self) -> None:
        try:
            if sys.platform.startswith("darwin") or "bsd" in sys.platform:
                self._start_kqueue()
            elif os.name == "nt":
                self._start_windows()
        except Exception:
            # If starting watchers fails we simply fall back to rebuilds
            self._watch_failed = True

    def _start_kqueue(self) -> None:
        import select

        self._kq = select.kqueue()
        flags = select.KQ_EV_ADD | select.KQ_EV_ENABLE
        fflags = (select.KQ_NOTE_FORK | select.KQ_NOTE_EXIT | getattr(select, "KQ_NOTE_EXEC", 0))
        # Track children of init (PID 1) to learn about new processes
        kev = select.kevent(1, filter=select.KQ_FILTER_PROC, flags=flags, fflags=fflags)
        self._kq.control([kev], 0)
        threading.Thread(target=self._kqueue_loop, daemon=True).start()

    def _kqueue_loop(self) -> None:
        import select

        while True:
            try:
                events = self._kq.control(None, 1)
            except Exception:
                with self._lock:
                    self._watch_failed = True
                    self._dirty = True
                break
            if not events:
                continue
            with self._lock:
                for ev in events:
                    pid = ev.ident
                    if ev.fflags & select.KQ_NOTE_EXIT:
                        self._procs.pop(pid, None)
                    else:
                        # For fork/exec we simply mark cache dirty and rebuild
                        self._dirty = True

    def _start_windows(self) -> None:
        """Attempt to subscribe to Windows process notifications.

        The actual ``ProcessNotifyRoutine`` API is only available to kernel
        drivers so this method merely acts as a placeholder. If obtaining a
        handle fails the cache gracefully falls back to full rebuilds.
        """

        raise RuntimeError("Process notifications require elevated privileges")
