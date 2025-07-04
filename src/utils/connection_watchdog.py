"""Watchdog for repeatedly blocked remote connections."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
import asyncio
import time
import json
from pathlib import Path

import psutil

from .process_blocker import ProcessBlocker
from .kill_utils import kill_process_tree
from .security import ActiveConnection
from . import security, security_log


@dataclass(slots=True)
class ConnectionRecord:
    """Tracking info for a blocked remote address."""

    pids: set[int]
    names: set[str] = field(default_factory=set)
    exes: set[str] = field(default_factory=set)
    attempts: int = 0
    last_seen: float = field(default_factory=time.time)
    blocked_firewall: bool = False


class ConnectionWatchdog:
    """Terminate processes that reconnect to blocked hosts."""

    def __init__(
        self,
        max_attempts: int = 3,
        blocker: ProcessBlocker | None = None,
        *,
        expiration: float | None = 300.0,
        firewall: bool = False,
        path: str | Path | None = None,
    ) -> None:
        self.path = Path(path).expanduser() if path else Path.home() / ".coolbox" / "blocked_hosts.json"
        self.records: dict[str, ConnectionRecord] = {}
        self.max_attempts = max_attempts
        self.blocker = blocker or ProcessBlocker()
        self.expiration = expiration
        self.firewall = firewall
        self._loaded = False
        self.load()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def list_records(self) -> dict[str, ConnectionRecord]:
        """Return the current blocked host records."""
        return self.records

    def remove(self, host: str) -> bool:
        """Remove ``host`` from the watch list."""
        rec = self.records.pop(host, None)
        if rec is None:
            return False
        if self.firewall and rec.blocked_firewall:
            if ":" in host:
                ip, port_str = host.split(":", 1)
                try:
                    port_num = int(port_str)
                except Exception:
                    port_num = None
                security.unblock_remote_firewall(ip, port_num)
            else:
                security.unblock_remote_firewall(host)
            security_log.add_security_event("firewall_unblock_remote", f"{host}")
        self.save()
        security_log.add_security_event("unblock_remote", host)
        return True

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load blocked hosts from disk if possible."""
        if self._loaded or not self.path:
            return
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text())
            except Exception:
                data = {}
            for host, rec in data.items():
                self.records[host] = ConnectionRecord(
                    set(rec.get("pids", [])),
                    set(rec.get("names", [])),
                    set(rec.get("exes", [])),
                    rec.get("attempts", 0),
                    rec.get("last_seen", time.time()),
                    rec.get("blocked_firewall", False),
                )
        self._loaded = True

    def save(self) -> None:
        """Persist the current blocked host list."""
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                host: {
                    "pids": sorted(rec.pids),
                    "names": sorted(rec.names),
                    "exes": sorted(rec.exes),
                    "attempts": rec.attempts,
                    "last_seen": rec.last_seen,
                    "blocked_firewall": rec.blocked_firewall,
                }
                for host, rec in self.records.items()
            }
            self.path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def add(
        self,
        host: str,
        pids: Iterable[int],
        names: Iterable[str] | None = None,
        exes: Iterable[str] | None = None,
    ) -> None:
        rec = self.records.setdefault(host, ConnectionRecord(set()))
        rec.pids.update(pids)
        if names:
            rec.names.update(n for n in names if n)
        if exes:
            rec.exes.update(e for e in exes if e)
        rec.last_seen = time.time()
        self.save()

    def check(self, conns: dict[str, list[ActiveConnection]]) -> None:
        now = time.time()
        changed = False
        for host in list(self.records):
            rec = self.records[host]
            if self.expiration is not None and now - rec.last_seen > self.expiration:
                if self.firewall and rec.blocked_firewall:
                    if ":" in host:
                        ip, port_str = host.split(":", 1)
                        try:
                            port_num = int(port_str)
                        except Exception:
                            port_num = None
                        security.unblock_remote_firewall(ip, port_num)
                    else:
                        security.unblock_remote_firewall(host)
                    security_log.add_security_event("firewall_unblock_remote", host)
                self.records.pop(host, None)
                security_log.add_security_event("host_expired", host)
                changed = True
                continue
            entries = conns.get(host) or []
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
                    security_log.add_security_event("kill_remote", f"pid {pid} host {host}")
                else:
                    try:
                        psutil.Process(pid).kill()
                        security_log.add_security_event("kill_remote", f"pid {pid} host {host}")
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
                security_log.add_security_event("escalate_remote", host)
                if self.firewall and not rec.blocked_firewall:
                    if ":" in host:
                        ip, port_str = host.split(":", 1)
                        try:
                            port_num = int(port_str)
                        except Exception:
                            port_num = None
                        security.block_remote_firewall(ip, port_num)
                    else:
                        security.block_remote_firewall(host)
                    rec.blocked_firewall = True
                    security_log.add_security_event("firewall_block_remote", host)
                changed = True
        if changed:
            self.save()

    def clear(self) -> None:
        """Remove all records and unblock firewall rules if needed."""
        if not self.records:
            return
        if self.firewall:
            for host, rec in list(self.records.items()):
                if rec.blocked_firewall:
                    if ":" in host:
                        ip, port_str = host.split(":", 1)
                        try:
                            port_num = int(port_str)
                        except Exception:
                            port_num = None
                        security.unblock_remote_firewall(ip, port_num)
                    else:
                        security.unblock_remote_firewall(host)
                    security_log.add_security_event("firewall_unblock_remote", host)
        self.records.clear()
        security_log.add_security_event("clear_hosts", "all")
        self.save()

    def expire(self) -> None:
        """Remove records that haven't been seen within ``expiration`` seconds."""
        if self.expiration is None:
            return
        now = time.time()
        changed = False
        for host in list(self.records):
            rec = self.records[host]
            if now - rec.last_seen > self.expiration:
                if self.firewall and rec.blocked_firewall:
                    if ":" in host:
                        ip, port_str = host.split(":", 1)
                        try:
                            port_num = int(port_str)
                        except Exception:
                            port_num = None
                        security.unblock_remote_firewall(ip, port_num)
                    else:
                        security.unblock_remote_firewall(host)
                    security_log.add_security_event("firewall_unblock_remote", host)
                self.records.pop(host, None)
                security_log.add_security_event("host_expired", host)
                changed = True
        if changed:
            self.save()

    # ------------------------------------------------------------------
    # Async wrappers
    # ------------------------------------------------------------------

    async def async_add(
        self,
        host: str,
        pids: Iterable[int],
        names: Iterable[str] | None = None,
        exes: Iterable[str] | None = None,
    ) -> None:
        await asyncio.to_thread(self.add, host, pids, names=names, exes=exes)

    async def async_check(self, conns: dict[str, list[ActiveConnection]]) -> None:
        await asyncio.to_thread(self.check, conns)

    async def async_remove(self, host: str) -> bool:
        return await asyncio.to_thread(self.remove, host)

    async def async_expire(self) -> None:
        await asyncio.to_thread(self.expire)

    async def async_clear(self) -> None:
        await asyncio.to_thread(self.clear)
