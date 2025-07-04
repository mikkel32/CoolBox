"""Process watchdog that aggressively kills targeted programs."""

from __future__ import annotations

from dataclasses import dataclass, field


import psutil
import json
from pathlib import Path

from .kill_utils import kill_process_tree


@dataclass(slots=True)
class BlockTarget:
    """Information about a blocked process."""

    name: str
    exe_paths: set[str] = field(default_factory=set)


class ProcessBlocker:
    """Aggressively terminate processes that match blocked names.

    Parameters
    ----------
    path:
        Optional path to persist the block list. If not provided, a file named
        ``blocked_processes.json`` in ``~/.coolbox`` is used.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else Path.home() / ".coolbox" / "blocked_processes.json"
        self.targets: dict[str, BlockTarget] = {}
        self._loaded: bool = False
        self.load()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load the block list from disk if a path is configured."""
        if self._loaded or not self.path:
            return
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text())
            except Exception:
                data = {}
            for name, paths in data.items():
                target = self.targets.setdefault(name, BlockTarget(name))
                target.exe_paths.update(paths)
        self._loaded = True

    def save(self) -> None:
        """Persist the block list if a path is configured."""
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {name: sorted(t.exe_paths) for name, t in self.targets.items()}
            self.path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def add_by_pid(self, pid: int) -> None:
        """Add the process identified by ``pid`` to the block list."""
        try:
            proc = psutil.Process(pid)
            name = proc.name()
            exe = proc.exe()
        except Exception:
            return
        self.add(name, exe)
        self.save()

    def add(self, name: str, exe: str | None = None) -> None:
        """Add ``name`` (and optional ``exe`` path) to the block list."""
        target = self.targets.setdefault(name, BlockTarget(name))
        if exe:
            target.exe_paths.add(exe)
        self.save()

    def remove(self, name: str, exe: str | None = None) -> bool:
        """Remove a blocked name or specific executable path."""
        if name not in self.targets:
            return False
        target = self.targets[name]
        if exe:
            if exe in target.exe_paths:
                target.exe_paths.remove(exe)
                if not target.exe_paths:
                    self.targets.pop(name, None)
                self.save()
                return True
            return False
        else:
            self.targets.pop(name, None)
            self.save()
            return True

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def list_targets(self) -> dict[str, BlockTarget]:
        """Return the current block list."""
        return self.targets

    def check(self) -> None:
        """Kill any running processes that match the block list."""
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            name = proc.info.get("name")
            if not name or name not in self.targets:
                continue
            target = self.targets[name]
            exe = proc.info.get("exe") or ""
            if target.exe_paths and exe not in target.exe_paths:
                continue
            kill_process_tree(proc.info["pid"])
