#!/usr/bin/env python3
"""Interactive CLI for inspecting executable files."""
from __future__ import annotations

import argparse
import datetime
import platform
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.prompt import Prompt  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.widgets import (
    DataTable,
    Header,
    Footer,
    TabPane,
    TabbedContent,
    Input,
)
from textual.containers import Container  # noqa: E402
import psutil  # noqa: E402

from src.utils.helpers import calc_hash  # noqa: E402
from src.utils.process_utils import run_command  # noqa: E402
from src.utils.security import ensure_admin, is_admin, list_open_ports  # noqa: E402
import pwd  # noqa: E402
import grp  # noqa: E402
import shutil  # noqa: E402


def _calc_hash_smart(path: Path) -> str:
    """Return SHA256 hash of *path* using fallbacks if direct reading fails."""
    try:
        return calc_hash(str(path), "sha256")
    except Exception as exc:
        if platform.system() == "Windows":
            out = run_command(["certutil", "-hashfile", str(path), "SHA256"], capture=True)
            if out:
                return out.split()[0]
        else:
            tool = shutil.which("sha256sum") or shutil.which("shasum")
            if tool:
                cmd = [tool]
                if Path(tool).name == "shasum":
                    cmd += ["-a", "256"]
                cmd.append(str(path))
                out = run_command(cmd, capture=True)
                if out:
                    return out.split()[0]
        return f"<unavailable: {exc}>"


def _powershell(cmd: str) -> str | None:
    """Run a PowerShell command and return its output."""
    return run_command([
        "powershell",
        "-NoProfile",
        "-Command",
        f"{cmd} -ErrorAction SilentlyContinue",
    ], capture=True)


def _windows_details(path: Path) -> Dict[str, str]:
    details: Dict[str, str] = {}
    details["SHA256"] = _calc_hash_smart(path)
    version = _powershell(f'(Get-Item \"{path}\").VersionInfo.ProductVersion')
    if version:
        details["Version"] = version.strip()
    desc = _powershell(f'(Get-Item \"{path}\").VersionInfo.FileDescription')
    if desc:
        details["Description"] = desc.strip()
    company = _powershell(f'(Get-Item \"{path}\").VersionInfo.CompanyName')
    if company:
        details["Company"] = company.strip()
    sig = _powershell(f'$(Get-AuthenticodeSignature \"{path}\").Status')
    if sig:
        details["Signature"] = sig.strip()
    return details


def _unix_details(path: Path) -> Dict[str, str]:
    details: Dict[str, str] = {}
    details["SHA256"] = _calc_hash_smart(path)
    file_type = run_command(["file", "-b", str(path)], capture=True)
    if file_type:
        details["Type"] = file_type.strip()
    return details


def _file_owner(path: Path) -> str | None:
    """Return owner of *path*."""
    try:
        if platform.system() == "Windows":
            owner = _powershell(f'(Get-Acl \"{path}\").Owner')
            return owner.strip() if owner else None
        stat = path.stat()
        user = pwd.getpwuid(stat.st_uid).pw_name
        group = grp.getgrgid(stat.st_gid).gr_name
        return f"{user}:{group}"
    except Exception:
        return None


def _extract_strings(path: Path, *, limit: int = 10, min_len: int = 4) -> List[str]:
    """Return a list of printable strings found in *path*."""
    try:
        data = path.read_bytes()
    except Exception:
        return []
    import re
    pattern = re.compile(rb"[ -~]{%d,}" % min_len)
    found = []
    for match in pattern.finditer(data):
        s = match.group().decode("ascii", "replace")
        if s not in found:
            found.append(s)
        if len(found) >= limit:
            break
    return found


def gather_info(path: Path) -> Dict[str, str]:
    info: Dict[str, str] = {
        "Path": str(path),
        "Exists": str(path.exists()),
    }
    if path.exists():
        try:
            stat = path.stat()
        except PermissionError:
            info["Access"] = "Denied"
            return info

        info.update(
            {
                "Size": f"{stat.st_size} bytes",
                "Modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "Created": datetime.datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "Owner": _file_owner(path) or "unknown",
            }
        )

        if platform.system() == "Windows":
            info.update(_windows_details(path))
        else:
            info.update(_unix_details(path))
    return info


def _processes_for(path: Path) -> List[psutil.Process]:
    result: List[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            exe = proc.info.get("exe") or ""
            if exe and Path(exe).resolve() == path.resolve():
                result.append(proc)
        except Exception:
            continue
    return result


def _ports_for(pids: List[int]) -> Dict[int, List[str]]:
    ports = list_open_ports()
    result: Dict[int, List[str]] = {}
    for port, items in ports.items():
        for entry in items:
            if entry.pid in pids:
                result.setdefault(port, []).append(entry.process)
    return result


def display(info: Dict[str, str], procs: List[psutil.Process], ports: Dict[int, List[str]], strings: List[str] | None = None) -> None:
    console = Console()
    table = Table(title="Executable Info", show_lines=True)
    table.add_column("Property", style="bold")
    table.add_column("Value")
    for k, v in info.items():
        table.add_row(k, v)
    console.print(table)

    if procs:
        pt = Table(title="Running Processes", show_lines=True)
        pt.add_column("PID", justify="right")
        pt.add_column("Name")
        for p in procs:
            try:
                pt.add_row(str(p.pid), p.name())
            except Exception:
                continue
        console.print(pt)

    if ports:
        port_table = Table(title="Listening Ports", show_lines=True)
        port_table.add_column("Port", justify="right")
        port_table.add_column("Process")
        for port, names in ports.items():
            port_table.add_row(str(port), ", ".join(names))
        console.print(port_table)

    if strings:
        st = Table(title="Strings", show_lines=True)
        st.add_column("Text")
        for s in strings:
            st.add_row(s)
        console.print(st)


class InspectorApp(App):
    """Textual application displaying inspection results with refresh and filtering."""

    CSS_PATH = Path(__file__).with_suffix(".tcss")

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("/", "filter_strings", "Filter Strings"),
    ]

    def __init__(self, info: Dict[str, str], procs: List[psutil.Process], ports: Dict[int, List[str]], strings: List[str] | None) -> None:
        super().__init__()
        self.info = info
        self.procs = procs
        self.ports = ports
        self.strings = strings or []
        self.strings_filter = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

        self.info_table = DataTable(zebra_stripes=True)
        self.info_table.add_column("Property")
        self.info_table.add_column("Value")

        self.procs_table = DataTable(zebra_stripes=True)
        self.procs_table.add_column("PID", width=6)
        self.procs_table.add_column("Name")

        self.port_table = DataTable(zebra_stripes=True)
        self.port_table.add_column("Port", width=6)
        self.port_table.add_column("Process")

        self.strings_table = DataTable(zebra_stripes=True)
        self.strings_table.add_column("Strings")

        self.filter_input = Input(placeholder="Filter strings", id="filter-input")
        self.filter_input.display = False

        tabs = TabbedContent(
            TabPane(self.info_table, id="info", title="Info"),
            TabPane(self.procs_table, id="procs", title="Processes"),
            TabPane(self.port_table, id="ports", title="Ports"),
            TabPane(self.strings_table, id="strings", title="Strings"),
        )
        yield Container(tabs, id="body")
        yield self.filter_input

    def on_mount(self) -> None:  # pragma: no cover - UI setup
        self.load_tables()

    def load_tables(self) -> None:
        """Populate tables from current state."""
        self.info_table.clear()
        for k, v in self.info.items():
            self.info_table.add_row(k, v)

        self.procs_table.clear()
        for p in self.procs:
            try:
                self.procs_table.add_row(str(p.pid), p.name())
            except Exception:
                continue

        self.port_table.clear()
        for port, names in self.ports.items():
            self.port_table.add_row(str(port), ", ".join(names))

        self._load_strings()

    def _load_strings(self) -> None:
        self.strings_table.clear()
        for s in self.filter_strings():
            self.strings_table.add_row(s)

    def filter_strings(self) -> List[str]:
        return [s for s in self.strings if self.strings_filter.lower() in s.lower()]

    def action_refresh(self) -> None:
        path = Path(self.info.get("Path", ""))
        if path.exists():
            self.procs = _processes_for(path)
            self.ports = _ports_for([p.pid for p in self.procs]) if self.procs else {}
        self.load_tables()

    def action_filter_strings(self) -> None:
        self.filter_input.display = True
        self.set_focus(self.filter_input)

    def on_input_submitted(self, event: Input.Submitted) -> None:  # pragma: no cover - UI interaction
        if event.input.id == "filter-input":
            self.strings_filter = event.value
            self.filter_input.value = ""
            self.filter_input.display = False
            self._load_strings()


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Inspect an executable file")
    parser.add_argument("exe", nargs="?", help="Path to executable")
    parser.add_argument(
        "--admin",
        action="store_true",
        help="Request administrator rights for process and port info",
    )
    parser.add_argument(
        "--strings",
        type=int,
        metavar="N",
        help="Display up to N printable strings from the file",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Launch interactive terminal UI",
    )
    args = parser.parse_args(argv)

    exe_arg = args.exe or Prompt.ask("Path to executable")
    exe_path = Path(exe_arg).expanduser()

    if args.admin and not is_admin():
        if not ensure_admin("Administrator access is required for process and port information."):
            sys.exit(1)

    info = gather_info(exe_path)
    procs = _processes_for(exe_path) if exe_path.exists() else []
    ports = _ports_for([p.pid for p in procs]) if procs else {}

    strings = _extract_strings(exe_path, limit=args.strings) if args.strings else None

    if args.tui:
        InspectorApp(info, procs, ports, strings).run()
    else:
        display(info, procs, ports, strings)


if __name__ == "__main__":
    main()
