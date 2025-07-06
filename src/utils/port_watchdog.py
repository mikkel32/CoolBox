from __future__ import annotations

"""Watchdog for repeatedly killed ports."""

from dataclasses import dataclass, field
from typing import Iterable
import asyncio
import time
import json
from pathlib import Path

from .process_blocker import ProcessBlocker

import psutil

from .kill_utils import kill_process_tree
from .security import LocalPort
from . import security, security_log


@dataclass(slots=True)
class PortRecord:
    """Tracking info for a blocked port."""

    pids: set[int]
    names: set[str] = field(default_factory=set)
    exes: set[str] = field(default_factory=set)
    attempts: int = 0
    last_seen: float = field(default_factory=time.time)
    blocked_firewall: bool = False


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
        firewall: bool = False,
        path: str | Path | None = None,
    ) -> None:
        self.path = Path(path).expanduser() if path else Path.home() / ".coolbox" / "blocked_ports.json"
        self.records: dict[int, PortRecord] = {}
        self.max_attempts = max_attempts
        self.blocker = blocker or ProcessBlocker()
        self.expiration = expiration
        self.firewall = firewall
        self._loaded = False
        self.load()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def list_records(self) -> dict[int, PortRecord]:
        """Return the current blocked port records."""
        return self.records

    def remove(self, port: int) -> bool:
        """Remove ``port`` from the watch list."""
        rec = self.records.pop(port, None)
        if rec is None:
            return False
        if self.firewall and rec.blocked_firewall:
            security.unblock_port_firewall(port)
            security_log.add_security_event("unblock_port", f"port {port}")
        self.save()
        return True

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load blocked ports from disk if possible."""
        if self._loaded or not self.path:
            return
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text())
            except Exception:
                data = {}
            for port_str, rec in data.items():
                port = int(port_str)
                self.records[port] = PortRecord(
                    set(rec.get("pids", [])),
                    set(rec.get("names", [])),
                    set(rec.get("exes", [])),
                    rec.get("attempts", 0),
                    rec.get("last_seen", time.time()),
                    rec.get("blocked_firewall", False),
                )
        self._loaded = True

    def save(self) -> None:
        """Persist the current blocked port list."""
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                str(port): {
                    "pids": sorted(rec.pids),
                    "names": sorted(rec.names),
                    "exes": sorted(rec.exes),
                    "attempts": rec.attempts,
                    "last_seen": rec.last_seen,
                    "blocked_firewall": rec.blocked_firewall,
                }
                for port, rec in self.records.items()
            }
            self.path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

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
        self.save()

    def check(self, ports: dict[int, list[LocalPort]]) -> None:
        now = time.time()
        changed = False
        for port in list(self.records):
            rec = self.records[port]
            if self.expiration is not None and now - rec.last_seen > self.expiration:
                if self.firewall and rec.blocked_firewall:
                    security.unblock_port_firewall(port)
                    security_log.add_security_event("firewall_unblock_port", f"port {port}")
                self.records.pop(port, None)
                security_log.add_security_event("port_expired", f"port {port}")
                changed = True
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
                    security_log.add_security_event("kill_port", f"pid {pid} port {port}")
                else:
                    # fall back to kill if tree kill fails
                    try:
                        psutil.Process(pid).kill()
                        security_log.add_security_event("kill_port", f"pid {pid} port {port}")
                    except Exception:
                        pass
            rec.pids.update(active_pids)
            if killed:
                rec.attempts += 1
                rec.last_seen = now
                changed = True
            if rec.attempts >= self.max_attempts:
                for pid in rec.pids:
                    self.blocker.add_by_pid(pid)
                for name in rec.names:
                    if rec.exes:
                        for exe in rec.exes:
                            self.blocker.add(name, exe)
                    else:
                        self.blocker.add(name)
                security_log.add_security_event("escalate_port", f"port {port}")
                if self.firewall and not rec.blocked_firewall:
                    security.block_port_firewall(port)
                    rec.blocked_firewall = True
                    security_log.add_security_event("firewall_block_port", f"port {port}")
                changed = True
        if changed:
            self.save()

    def expire(self) -> None:
        """Remove records that haven't been seen within ``expiration`` seconds."""
        if self.expiration is None:
            return
        now = time.time()
        changed = False
        for port in list(self.records):
            rec = self.records[port]
            if now - rec.last_seen > self.expiration:
                if self.firewall and rec.blocked_firewall:
                    security.unblock_port_firewall(port)
                    security_log.add_security_event("firewall_unblock_port", f"port {port}")
                self.records.pop(port, None)
                security_log.add_security_event("port_expired", f"port {port}")
                changed = True
        if changed:
            self.save()

    def clear(self) -> None:
        """Remove all records and unblock firewall rules if needed."""
        if not self.records:
            return
        if self.firewall:
            for port, rec in list(self.records.items()):
                if rec.blocked_firewall:
                    security.unblock_port_firewall(port)
                    security_log.add_security_event("firewall_unblock_port", f"port {port}")
        self.records.clear()
        security_log.add_security_event("clear_ports", "all")
        self.save()

    # ------------------------------------------------------------------
    # Async wrappers
    # ------------------------------------------------------------------

    async def async_add(
        self,
        port: int,
        pids: Iterable[int],
        names: Iterable[str] | None = None,
        exes: Iterable[str] | None = None,
    ) -> None:
        await asyncio.to_thread(self.add, port, pids, names=names, exes=exes)

    async def async_check(self, ports: dict[int, list[LocalPort]]) -> None:
        await asyncio.to_thread(self.check, ports)

    async def async_remove(self, port: int) -> bool:
        return await asyncio.to_thread(self.remove, port)

    async def async_expire(self) -> None:
        await asyncio.to_thread(self.expire)

    async def async_clear(self) -> None:
        await asyncio.to_thread(self.clear)
