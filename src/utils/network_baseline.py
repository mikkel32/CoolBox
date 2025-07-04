from __future__ import annotations

"""Baseline tracking for network ports and remote hosts."""

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Iterable, Tuple, Set

from . import security_log


@dataclass(slots=True)
class NetworkBaseline:
    """Persist known ports and remote hosts for anomaly detection."""

    ports: Set[int] = field(default_factory=set)
    hosts: Set[str] = field(default_factory=set)
    path: Path = field(default_factory=lambda: Path.home() / ".coolbox" / "baseline.json")
    _loaded: bool = field(default=False, init=False)

    def load(self) -> None:
        if self._loaded:
            return
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text())
                self.ports.update(map(int, data.get("ports", [])))
                self.hosts.update(data.get("hosts", []))
            except Exception:
                pass
        self._loaded = True

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "ports": sorted(self.ports),
                "hosts": sorted(self.hosts),
            }
            self.path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def diff(
        self,
        ports: Iterable[int],
        hosts: Iterable[str],
        *,
        update: bool = False,
    ) -> Tuple[Set[int], Set[str]]:
        """Return ports and hosts not present in the baseline.

        If *update* is ``True`` unknown items are added to the baseline and
        persisted to disk.
        """
        self.load()
        new_ports = set(ports) - self.ports
        new_hosts = set(hosts) - self.hosts
        if update and (new_ports or new_hosts):
            self.ports.update(new_ports)
            self.hosts.update(new_hosts)
            self.save()
            security_log.add_security_event(
                "baseline_update",
                f"ports:{len(new_ports)} hosts:{len(new_hosts)}",
            )
        return new_ports, new_hosts

    def clear(self) -> None:
        self.ports.clear()
        self.hosts.clear()
        self.save()
        security_log.add_security_event("baseline_clear", "all")
