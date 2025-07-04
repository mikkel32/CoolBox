from __future__ import annotations

"""Watchdog for repeatedly killed ports."""

from dataclasses import dataclass, field
from typing import Iterable
import time

from .process_blocker import ProcessBlocker

import psutil

from .kill_utils import kill_process_tree
from .security import LocalPort


@dataclass(slots=True)
class PortRecord:
    """Tracking info for a blocked port."""

    pids: set[int]
    names: set[str] = field(default_factory=set)
    exes: set[str] = field(default_factory=set)
    attempts: int = 0
    last_seen: float = field(default_factory=time.time)


class PortWatchdog:
    """Terminate processes that reopen blocked ports.

    If a port is killed ``max_attempts`` times the associated process name is
    forwarded to a :class:`~src.utils.process_blocker.ProcessBlocker` instance
    which aggressively terminates any future instances.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        blocker: ProcessBlocker | None = None,
        *,
        expiration: float | None = 300.0,
    ) -> None:
        self.records: dict[int, PortRecord] = {}
        self.max_attempts = max_attempts
        self.blocker = blocker or ProcessBlocker()
        self.expiration = expiration

    def add(
        self,
        port: int,
        pids: Iterable[int],
        names: Iterable[str] | None = None,
        exes: Iterable[str] | None = None,
    ) -> None:
        rec = self.records.setdefault(port, PortRecord(set()))
        rec.pids.update(pids)
        if names:
            rec.names.update(n for n in names if n)
        if exes:
            rec.exes.update(e for e in exes if e)
        rec.last_seen = time.time()

    def check(self, ports: dict[int, list[LocalPort]]) -> None:
        now = time.time()
        for port in list(self.records):
            rec = self.records[port]
            if self.expiration is not None and now - rec.last_seen > self.expiration:
                self.records.pop(port, None)
                continue
            entries = ports.get(port) or []
            if entries:
                rec.last_seen = now
            active_pids = {e.pid for e in entries if e.pid is not None}
            rec.names.update(e.process for e in entries if e.process)
            rec.exes.update(e.exe for e in entries if e.exe)
            targets = rec.pids | active_pids
            killed = False
            for pid in list(targets):
                if pid is None or not psutil.pid_exists(pid):
                    continue
                if kill_process_tree(pid):
                    killed = True
                else:
                    # fall back to kill if tree kill fails
                    try:
                        psutil.Process(pid).kill()
                    except Exception:
                        pass
            rec.pids.update(active_pids)
            if killed:
                rec.attempts += 1
                rec.last_seen = now
            still_alive = any(psutil.pid_exists(p) for p in rec.pids)
            if rec.attempts >= self.max_attempts:
                self.records.pop(port, None)
                for pid in rec.pids:
                    self.blocker.add_by_pid(pid)
                for name in rec.names:
                    if rec.exes:
                        for exe in rec.exes:
                            self.blocker.add(name, exe)
                    else:
                        self.blocker.add(name)

    def expire(self) -> None:
        """Remove records that haven't been seen within ``expiration`` seconds."""
        if self.expiration is None:
            return
        now = time.time()
        for port in list(self.records):
            rec = self.records[port]
            if now - rec.last_seen > self.expiration:
                self.records.pop(port, None)

