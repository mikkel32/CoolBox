#!/usr/bin/env python3
"""Interactive CLI for inspecting executable files."""
from __future__ import annotations

import argparse
import datetime
import platform
import sys
from pathlib import Path
from typing import Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.prompt import Prompt  # noqa: E402
from typing import Any
import shlex

try:  # pragma: no cover - optional dependency
    from textual.app import App, ComposeResult  # type: ignore
    from textual.widgets import (
        DataTable,
        Header,
        Footer,
        TabPane,
        TabbedContent,
        Input,
    )
    from textual.containers import Container

    TEXTUAL_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - textual is optional
    App = ComposeResult = DataTable = Header = Footer = TabPane = TabbedContent = Input = Container = Any  # type: ignore
    TEXTUAL_AVAILABLE = False
import psutil  # noqa: E402

from src.utils.helpers import calc_hash  # noqa: E402
from src.utils.process_utils import run_command, run_command_ex  # noqa: E402
from src.utils.security import ensure_admin, is_admin, list_open_ports  # noqa: E402
import shutil  # noqa: E402
import hashlib
import ctypes
import ctypes.util
import os
import re

HASHCALC_BIN_DEFAULT = Path(__file__).with_name("hash_calc")
LIB_EXT = {
    "win32": ".dll",
    "darwin": ".dylib",
}.get(sys.platform, ".so")
HASHCALC_LIB_DEFAULT = Path(__file__).with_name("hash_calc" + LIB_EXT)
HASHCALC_SRC = Path(__file__).with_name("hash_calc.cpp")
_HASH_LIB = None


def _cxx() -> str | None:
    """Return the C++ compiler to use, honoring the CXX environment variable."""
    env = os.getenv("CXX")
    if env:
        return env
    for c in ("g++", "clang++"):
        path = shutil.which(c)
        if path:
            return path
    return None


def _hashcalc_bin() -> Path:
    env = os.getenv("EXE_HASH_BIN")
    return Path(env) if env else HASHCALC_BIN_DEFAULT


def _hashcalc_lib() -> Path:
    env = os.getenv("EXE_HASH_LIB")
    return Path(env) if env else HASHCALC_LIB_DEFAULT


def _extra_cxxflags() -> list[str]:
    """Return additional C++ flags from the ``EXE_HASH_CXXFLAGS`` env var."""
    env = os.getenv("EXE_HASH_CXXFLAGS")
    return shlex.split(env) if env else []


def _openssl_flags() -> list[str]:
    """Return compiler/linker flags for OpenSSL.

    Tries ``pkg-config`` first and falls back to ``openssl version`` and
    :func:`ctypes.util.find_library` when pkg-config is unavailable.
    """

    flags: list[str] = []
    cflags = run_command(
        ["pkg-config", "--cflags", "openssl"], capture=True, check=False
    )
    libs = run_command(["pkg-config", "--libs", "openssl"], capture=True, check=False)

    if cflags:
        flags.extend(shlex.split(cflags))
    else:
        out = run_command(["openssl", "version", "-d"], capture=True, check=False)
        if out:
            m = re.search(r'"([^"]+)"', out)
            if m:
                inc = Path(m.group(1)) / "include"
                flags.append(f"-I{inc}")

    if libs:
        flags.extend(shlex.split(libs))
    else:
        lib = ctypes.util.find_library("crypto")
        if lib and "/" in lib:
            flags.append(f"-L{Path(lib).resolve().parent}")
        flags.append("-lcrypto")

    return flags


def _compile_hash_calc() -> bool:
    """Compile the C++ hash library/CLI if needed."""
    compiler = _cxx()
    if not compiler or not HASHCALC_SRC.exists():
        return False

    flags = _openssl_flags()
    extra = _extra_cxxflags()

    dest_lib = _hashcalc_lib()
    dest_bin = _hashcalc_bin()
    newer = lambda p: not p.exists() or p.stat().st_mtime < HASHCALC_SRC.stat().st_mtime
    if newer(dest_lib):
        cmd = [
            compiler,
            "-std=c++17",
            "-shared",
            "-fPIC",
            str(HASHCALC_SRC),
            "-o",
            str(dest_lib),
            *flags,
            *extra,
        ]
        run_command(cmd, capture=False)

    if newer(dest_bin):
        cmd = [
            compiler,
            "-std=c++17",
            "-DBUILD_CLI",
            str(HASHCALC_SRC),
            "-o",
            str(dest_bin),
            *flags,
            *extra,
        ]
        run_command(cmd, capture=False)

    return dest_lib.exists()


def _load_hash_lib() -> ctypes.CDLL | None:
    """Load the compiled hash library if available."""
    global _HASH_LIB
    if _HASH_LIB is not None:
        return _HASH_LIB
    lib_path = _hashcalc_lib()
    candidates: list[str] = []
    if lib_path.exists():
        candidates.append(str(lib_path))
    else:
        found = ctypes.util.find_library("hash_calc")
        if found:
            candidates.append(found)
    for cand in candidates:
        try:
            lib = ctypes.CDLL(cand)
            lib.hash_file.argtypes = [
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_size_t,
            ]
            lib.hash_file.restype = ctypes.c_int
            _HASH_LIB = lib
            return lib
        except Exception:
            continue
    if not _compile_hash_calc():
        return None
    lib_path = _hashcalc_lib()
    try:
        lib = ctypes.CDLL(str(lib_path))
        lib.hash_file.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_size_t,
        ]
        lib.hash_file.restype = ctypes.c_int
        _HASH_LIB = lib
        return lib
    except Exception:
        return None


def _calc_hash_cpp(path: Path, algo: str) -> str | None:
    """Return hash using the C++ helper if available."""
    lib = _load_hash_lib()
    if lib:
        buf = ctypes.create_string_buffer(129)
        res = lib.hash_file(algo.encode(), str(path).encode(), buf, len(buf))
        if res == 0:
            return buf.value.decode()
    if not _compile_hash_calc():
        return None
    out = run_command([str(_hashcalc_bin()), algo, str(path)], capture=True)
    return out.strip() if out else None


def _calc_hash_smart(path: Path, algo: str = "sha256") -> str:
    """Return hash of *path* using *algo* with several fallbacks."""
    cpp = _calc_hash_cpp(path, algo)
    if cpp:
        return cpp
    try:
        return calc_hash(str(path), algo)
    except Exception as exc:
        if platform.system() == "Windows":
            win_algo = algo.upper()
            out = run_command(
                ["certutil", "-hashfile", str(path), win_algo], capture=True
            )
            if out:
                return out.split()[0]
        else:
            tool = None
            if algo == "md5":
                tool = shutil.which("md5sum") or shutil.which("md5")
            elif algo == "sha1":
                tool = shutil.which("sha1sum") or shutil.which("shasum")
            elif algo == "sha256":
                tool = shutil.which("sha256sum") or shutil.which("shasum")
            if tool:
                cmd = [tool]
                if Path(tool).name == "shasum" and algo != "md5":
                    if algo == "sha1":
                        cmd += ["-a", "1"]
                    elif algo == "sha256":
                        cmd += ["-a", "256"]
                cmd.append(str(path))
                out = run_command(cmd, capture=True)
                if out:
                    return out.split()[0]
        return f"<unavailable: {exc}>"


def _powershell(cmd: str) -> str | None:
    """Run a PowerShell command and return its output."""
    return run_command(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"{cmd} -ErrorAction SilentlyContinue",
        ],
        capture=True,
    )


def _windows_details(path: Path, algos: Sequence[str]) -> Dict[str, str]:
    details: Dict[str, str] = {}
    for algo in algos:
        details[algo.upper()] = _calc_hash_smart(path, algo)
    version = _powershell(f'(Get-Item "{path}").VersionInfo.ProductVersion')
    if version:
        details["Version"] = version.strip()
    desc = _powershell(f'(Get-Item "{path}").VersionInfo.FileDescription')
    if desc:
        details["Description"] = desc.strip()
    company = _powershell(f'(Get-Item "{path}").VersionInfo.CompanyName')
    if company:
        details["Company"] = company.strip()
    sig = _powershell(f'$(Get-AuthenticodeSignature "{path}").Status')
    if sig:
        details["Signature"] = sig.strip()
    return details


def _unix_details(path: Path, algos: Sequence[str]) -> Dict[str, str]:
    details: Dict[str, str] = {}
    for algo in algos:
        details[algo.upper()] = _calc_hash_smart(path, algo)
    file_type = run_command(["file", "-b", str(path)], capture=True)
    if file_type:
        details["Type"] = file_type.strip()
    return details


def _file_owner(path: Path) -> str | None:
    """Return owner of *path*."""
    try:
        if platform.system() == "Windows":
            owner = _powershell(f'(Get-Acl "{path}").Owner')
            return owner.strip() if owner else None
        import pwd
        import grp

        stat = path.stat()
        user = pwd.getpwuid(stat.st_uid).pw_name
        group = grp.getgrgid(stat.st_gid).gr_name
        return f"{user}:{group}"
    except Exception:
        return None


def _file_permissions(path: Path) -> str | None:
    """Return file permission bits for *path* as an octal string."""
    try:
        mode = path.stat().st_mode
        return oct(mode & 0o777)
    except Exception:
        return None


def _file_mode_text(path: Path) -> str | None:
    """Return symbolic permission bits for *path* (e.g. ``-rwxr-xr-x``)."""
    try:
        import stat as stat_mod

        return stat_mod.filemode(path.stat().st_mode)
    except Exception:
        return None


def _symlink_target(path: Path) -> str | None:
    """Return symlink target for *path* if it is a link."""
    try:
        if _is_symlink(path):
            return os.readlink(path)
    except Exception:
        return None
    return None


def _shebang_interpreter(path: Path) -> str | None:
    """Return interpreter path from a script's shebang line.

    Supports ``#!/usr/bin/env python`` style shebangs by resolving the
    interpreter with :func:`shutil.which` when possible.
    """
    try:
        with path.open("rb") as fh:
            first = fh.readline().decode("utf-8", "ignore").strip()
        if not first.startswith("#!"):
            return None
        import shlex

        parts = shlex.split(first[2:].strip())
        if not parts:
            return None
        cmd = parts[0]
        if Path(cmd).name == "env" and len(parts) > 1:
            resolved = shutil.which(parts[1])
            return resolved or parts[1]
        return cmd
    except Exception:
        return None
    return None


def _is_symlink(path: Path) -> bool:
    """Safely check whether *path* is a symlink."""
    try:
        return path.is_symlink()
    except Exception:
        return False


def _detect_architecture(path: Path) -> str | None:
    """Return "32-bit" or "64-bit" if *path* looks like a PE or ELF binary."""
    try:
        with path.open("rb") as fh:
            magic = fh.read(0x40)
        if magic.startswith(b"\x7fELF"):
            cls = magic[4]
            return "64-bit" if cls == 2 else "32-bit"
        if magic.startswith(b"MZ") and len(magic) > 0x3C:
            offset = int.from_bytes(magic[0x3C:0x40], "little")
            with path.open("rb") as fh:
                fh.seek(offset)
                hdr = fh.read(6)
            if hdr[:4] != b"PE\0\0" or len(hdr) < 6:
                return None
            machine = int.from_bytes(hdr[4:6], "little")
            if machine in {0x8664, 0x200, 0xaa64}:
                return "64-bit"
            if machine in {0x14C, 0x1c0}:
                return "32-bit"
    except Exception:
        return None
    return None


def _linked_libraries(path: Path) -> list[str] | None:
    """Return a list of dynamic libraries used by *path* if possible."""
    if platform.system() == "Windows":
        return None
    cmd = ["otool", "-L", str(path)] if sys.platform == "darwin" else ["ldd", str(path)]
    out = run_command(cmd, capture=True, check=False)
    if not out:
        return None

    libs: list[str] = []
    for line in out.splitlines()[1:] if "darwin" in sys.platform else out.splitlines():
        line = line.strip()
        if not line:
            continue
        if sys.platform == "darwin":
            libs.append(line.split(" ")[0])
        else:
            if "=>" in line:
                libs.append(line.split("=>")[0].strip())
            else:
                libs.append(line.split()[0])
    return libs if libs else None


def _rpath_entries(path: Path) -> list[str] | None:
    """Return RPATH/RUNPATH entries for *path* if available."""
    if platform.system() == "Windows":
        return None
    if sys.platform == "darwin":
        out = run_command(["otool", "-l", str(path)], capture=True, check=False)
        if not out:
            return None
        rpaths: list[str] = []
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if "LC_RPATH" in line:
                for j in range(i + 1, min(i + 5, len(lines))):
                    m = re.search(r"path (.+?) \(offset", lines[j])
                    if m:
                        rpaths.append(m.group(1).strip())
                        break
        return rpaths if rpaths else None
    out = run_command(["readelf", "-d", str(path)], capture=True, check=False)
    if not out:
        return None
    rpaths = []
    for line in out.splitlines():
        if "(RPATH)" in line or "(RUNPATH)" in line:
            m = re.search(r"\[(.*?)\]", line)
            if m:
                rpaths.append(m.group(1))
    return rpaths if rpaths else None


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


def gather_info(path: Path, *, algos: Sequence[str] = ("sha256",)) -> Dict[str, str]:
    info: Dict[str, str] = {
        "Path": str(path),
        "Absolute": str(path.resolve(strict=False)),
        "Exists": str(path.exists()),
        "IsSymlink": str(_is_symlink(path)),
    }
    target = _symlink_target(path)
    if target:
        info["Target"] = target
    info["Executable"] = str(os.access(path, os.X_OK))
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
                "Accessed": datetime.datetime.fromtimestamp(stat.st_atime).isoformat(),
                "Created": datetime.datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "Owner": _file_owner(path) or "unknown",
                "Permissions": _file_permissions(path) or "unknown",
                "Mode": _file_mode_text(path) or "unknown",
            }
        )

        arch = _detect_architecture(path)
        if arch:
            info["Architecture"] = arch

        interp = _shebang_interpreter(path)
        if interp:
            info["Interpreter"] = interp

        libs = _linked_libraries(path)
        if libs:
            info["Libraries"] = ", ".join(libs)

        rpaths = _rpath_entries(path)
        if rpaths:
            info["RPATH"] = ", ".join(rpaths)

        if platform.system() == "Windows":
            info.update(_windows_details(path, algos))
        else:
            info.update(_unix_details(path, algos))

        try:
            stat = path.stat()
            info["Accessed"] = datetime.datetime.fromtimestamp(stat.st_atime).isoformat()
        except Exception:
            pass
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


def display(
    info: Dict[str, str],
    procs: List[psutil.Process],
    ports: Dict[int, List[str]],
    strings: List[str] | None = None,
) -> None:
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
        ("c", "toggle_cmd", "Run Command"),
    ]

    def __init__(
        self,
        info: Dict[str, str],
        procs: List[psutil.Process],
        ports: Dict[int, List[str]],
        strings: List[str] | None,
    ) -> None:
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

        self.cmd_table = DataTable(zebra_stripes=True)
        self.cmd_table.add_column("Output")

        self.cmd_input = Input(placeholder="Shell command", id="cmd-input")
        self.cmd_input.display = False

        self.filter_input = Input(placeholder="Filter strings", id="filter-input")
        self.filter_input.display = False

        tabs = TabbedContent(
            TabPane(self.info_table, id="info", title="Info"),
            TabPane(self.procs_table, id="procs", title="Processes"),
            TabPane(self.port_table, id="ports", title="Ports"),
            TabPane(self.strings_table, id="strings", title="Strings"),
            TabPane(self.cmd_table, id="shell", title="Shell"),
        )
        yield Container(tabs, id="body")
        yield self.filter_input
        yield self.cmd_input

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

    def action_toggle_cmd(self) -> None:
        self.cmd_input.display = True
        self.set_focus(self.cmd_input)

    def on_input_submitted(
        self, event: Input.Submitted
    ) -> None:  # pragma: no cover - UI interaction
        if event.input.id == "filter-input":
            self.strings_filter = event.value
            self.filter_input.value = ""
            self.filter_input.display = False
            self._load_strings()
        elif event.input.id == "cmd-input":
            self._run_shell_command(event.value)
            self.cmd_input.value = ""
            self.cmd_input.display = False

    def _run_shell_command(self, command: str) -> None:
        """Execute *command* and render its output in the table."""
        if command.strip().lower() in {"clear", "cls"}:
            self.cmd_table.clear()
            return

        ts = datetime.datetime.now().strftime("[%H:%M:%S] $ ")
        self.cmd_table.add_row(ts + command)

        out, rc = run_command_ex(shlex.split(command), capture=True, check=False)
        if out is None:
            self.cmd_table.add_row("<error>")
            return

        lines = out.splitlines()
        if not lines:
            self.cmd_table.add_row("<no output>")
        else:
            for line in lines:
                self.cmd_table.add_row(line)
        if rc is not None:
            self.cmd_table.add_row(f"[exit {rc}]")


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
        "--hashes",
        default="sha256",
        help="Comma-separated list of hash algorithms to compute",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Launch interactive terminal UI (requires 'textual')",
    )
    args = parser.parse_args(argv)

    exe_arg = args.exe or Prompt.ask("Path to executable")
    exe_path = Path(exe_arg).expanduser()

    if args.admin and not is_admin():
        if not ensure_admin(
            "Administrator access is required for process and port information."
        ):
            sys.exit(1)

    algos = [a.strip().lower() for a in args.hashes.split(",") if a.strip()]
    info = gather_info(exe_path, algos=algos)
    procs = _processes_for(exe_path) if exe_path.exists() else []
    ports = _ports_for([p.pid for p in procs]) if procs else {}

    strings = _extract_strings(exe_path, limit=args.strings) if args.strings else None

    if args.tui:
        if not TEXTUAL_AVAILABLE:
            print(
                "The 'textual' package is required for TUI mode.\n"
                "Falling back to plain output."
            )
            display(info, procs, ports, strings)
        else:
            InspectorApp(info, procs, ports, strings).run()
    else:
        display(info, procs, ports, strings)


if __name__ == "__main__":
    main()
