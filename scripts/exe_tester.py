#!/usr/bin/env python3
"""Stress test an executable using CoolBox security utilities."""

from __future__ import annotations

import argparse
import asyncio
import os
import platform
import sys
import time
from pathlib import Path
from subprocess import Popen
import subprocess
import shutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils import security  # noqa: E402
from src.utils import security_log, MatrixBorder  # noqa: E402
from src.utils.win_console import hidden_creation_flags, spawn_detached  # noqa: E402
from rich.console import Console, Group  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.progress import Progress  # noqa: E402
from rich.live import Live  # noqa: E402
from rich.text import Text  # noqa: E402

DEFAULT_MESSAGE = "EXECUTABLE  STRESS  TESTER"

MATRIX_ART = [
    r"    _              _     ",
    r"   / \\   ___  __ _(_)___ ",
    r"  / _ \\ / _ \\/ _` | / __|",
    r" / ___ \\  __/ (_| | \\__ \",",
    r"/_/   \\_\\___|\\__, |_|___/",
    r"             |___/       ",
    r"",
    r"   {msg}  ",
]


def render_header(console: Console) -> None:
    """Print the static ASCII header."""
    msg = os.environ.get("MATRIX_MESSAGE", DEFAULT_MESSAGE)
    for line in MATRIX_ART:
        console.print(Text(line.format(msg=msg), style="green"))


def run_powershell(command: str, *, capture: bool = False) -> str | None:
    """Execute ``command`` via PowerShell with numerous fallbacks."""
    system = platform.system()
    if system != "Windows":
        exe = (
            shutil.which("pwsh")
            or shutil.which("pwsh-preview")
            or shutil.which("powershell")
            or shutil.which("powershell-preview")
        )
        if exe:
            try:
                cp = subprocess.run(
                    [exe, "-Command", command],
                    capture_output=capture,
                    text=True,
                    check=False,
                )
                if cp.returncode == 0:
                    return cp.stdout if capture else ""
            except Exception as exc:  # pragma: no cover - best effort
                security_log.add_event("exe_test", f"nonwin powershell failed: {exc}")
        return None

    attempts: list[list[str]] = []
    attempts.append(["powershell", "-Command", command])
    attempts.append(["pwsh", "-Command", command])

    cmd_path = Path(command)
    if cmd_path.is_file() and cmd_path.suffix.lower() == ".ps1":
        attempts.insert(0, ["pwsh", "-File", command])
        attempts.insert(
            0,
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                command,
            ],
        )
    attempts.append(["powershell", "-NoProfile", "-Command", command])
    attempts.append(["pwsh", "-NoProfile", "-Command", command])
    attempts.append([
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
    ])

    comspec = os.environ.get("COMSPEC")
    if comspec:
        attempts.append([comspec, "/c", "powershell", "-Command", command])

    pwsh_env = os.environ.get("PWSH")
    if pwsh_env:
        attempts.append([pwsh_env, "-Command", command])

    root_dir = Path(os.environ.get("SystemRoot", r"C:\\Windows"))
    for sub in ("System32", "Sysnative", "SysWOW64"):
        ps_exe = root_dir / sub / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if ps_exe.is_file():
            attempts.append([str(ps_exe), "-Command", command])

    for pf_var in (
        "ProgramFiles",
        "ProgramFiles(x86)",
        "ProgramW6432",
        "ProgramFilesArm",
    ):
        pf = os.environ.get(pf_var)
        if pf:
            for subdir in ("PowerShell\\7", "PowerShell\\6", "PowerShell\\7-preview"):
                for exe_name in (
                    "pwsh.exe",
                    "pwsh-preview.exe",
                    "powershell.exe",
                    "powershell-preview.exe",
                ):
                    exe = Path(pf) / subdir / exe_name
                    if exe.is_file():
                        attempts.append([str(exe), "-Command", command])

    pshome = os.environ.get("PSHOME")
    if pshome:
        exe = Path(pshome) / "powershell.exe"
        if exe.is_file():
            attempts.append([str(exe), "-Command", command])
        exe = Path(pshome) / "pwsh.exe"
        if exe.is_file():
            attempts.append([str(exe), "-Command", command])

    env_ps = os.environ.get("POWERSHELL_EXE")
    if env_ps:
        exe = Path(env_ps)
        if exe.is_file():
            attempts.insert(0, [str(exe), "-Command", command])

    for mod_path in os.environ.get("PSModulePath", "").split(os.pathsep):
        base = Path(mod_path).parent
        exe = base / "powershell.exe"
        if exe.is_file():
            attempts.append([str(exe), "-Command", command])

    if shutil.which("where"):
        try:
            cp = subprocess.run(
                ["where", "powershell"], capture_output=True, text=True, check=False
            )
            if cp.returncode == 0:
                for line in cp.stdout.splitlines():
                    exe = Path(line.strip())
                    if exe.is_file():
                        attempts.append([str(exe), "-Command", command])
        except Exception as exc:
            security_log.add_event("exe_test", f"where powershell failed: {exc}")

    for entry in os.environ.get("PATH", "").split(os.pathsep):
        for exe in ("powershell.exe", "pwsh.exe"):
            candidate = Path(entry) / exe
            if candidate.is_file():
                attempts.append([str(candidate), "-Command", command])

    if shutil.which("wsl"):
        attempts.append(["wsl", "powershell.exe", "-Command", command])
        attempts.append(["wsl", "pwsh", "-Command", command])

    if comspec:
        attempts.append([comspec, "/k", "powershell", "-Command", command])

    py_launcher = shutil.which("py")
    if py_launcher:
        attempts.append([py_launcher, "-3", "-m", "powershell", "-Command", command])

    for cmd in attempts:
        out = security._run(cmd, capture=capture)
        if out is not None:
            return out
        security_log.add_event("exe_test", f"powershell attempt failed: {cmd}")

    if comspec:
        out = security._run([comspec, "/c", command], capture=capture)
        if out is not None:
            return out
        security_log.add_event("exe_test", f"cmd shell failed: {command}")

    try:
        cp = subprocess.run(
            ["powershell", "-Command", command],
            capture_output=capture,
            text=True,
            check=False,
        )
        if cp.returncode == 0:
            return cp.stdout if capture else ""
    except Exception as exc:
        security_log.add_event("exe_test", f"final powershell failed: {exc}")

    if comspec:
        try:
            cp = subprocess.run(
                [comspec, "/c", "start", "/wait", "powershell", "-Command", command],
                capture_output=capture,
                text=True,
                check=False,
            )
            if cp.returncode == 0:
                return cp.stdout if capture else ""
        except Exception as exc:
            security_log.add_event("exe_test", f"start fallback failed: {exc}")

    if shutil.which("dotnet"):
        try:
            cp = subprocess.run(
                ["dotnet", "tool", "run", "powershell", "-Command", command],
                capture_output=capture,
                text=True,
                check=False,
            )
            if cp.returncode == 0:
                return cp.stdout if capture else ""
        except Exception as exc:
            security_log.add_event("exe_test", f"dotnet tool failed: {exc}")

    try:
        cp = subprocess.run(
            f"powershell -Command \"{command}\"",
            shell=True,
            capture_output=capture,
            text=True,
            check=False,
        )
        if cp.returncode == 0:
            return cp.stdout if capture else ""
    except Exception as exc:
        security_log.add_event("exe_test", f"shell powershell failed: {exc}")

    if security.run_command_background(["powershell", "-Command", command]):
        return ""

    try:
        spawn_detached(["powershell", "-Command", command])
        return ""
    except Exception as exc:  # pragma: no cover - best effort
        security_log.add_event("exe_test", f"detached powershell failed: {exc}")

    return None


def launch_exe(path: Path, *, hidden: bool = False) -> Popen:
    """Launch *path* and return the process object."""
    kwargs = {}
    if hidden:
        kwargs["creationflags"] = hidden_creation_flags(detach=False)
    return Popen([str(path)], stdout=None, stderr=None, **kwargs)


def smart_terminate(proc: Popen, *, tree: bool = False) -> bool:
    """Terminate ``proc`` gracefully with fallbacks."""
    try:
        proc.terminate()
        proc.wait(timeout=3)
        return True
    except Exception:
        pass
    try:
        return security.kill_process_tree(proc.pid) if tree else security.kill_process(proc.pid)
    except Exception as exc:
        security_log.add_event("exe_test", f"terminate failed: {exc}")
        return False


def smart_launch_exe(path: Path, *, hidden: bool = False) -> Popen | None:
    """Attempt to launch *path* using multiple strategies."""
    attempts: list[tuple[str, callable[[], Popen]]] = []

    # Extension specific helpers
    ext = path.suffix.lower()
    if ext in {".py", ".pyw"}:
        attempts.append(
            (
                "python",
                lambda: Popen(
                    [sys.executable, str(path)],
                    stdout=None,
                    stderr=None,
                    **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                ),
            )
        )
        py3 = shutil.which("python3")
        if py3 and py3 != sys.executable:
            attempts.append(
                (
                    "python3",
                    lambda p=py3: Popen(
                        [p, str(path)],
                        stdout=None,
                        stderr=None,
                        **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                    ),
                )
            )
        py_launcher = shutil.which("py")
        if platform.system() == "Windows" and py_launcher:
            attempts.append(
                (
                    "py",
                    lambda pl=py_launcher: Popen(
                        [pl, str(path)],
                        stdout=None,
                        stderr=None,
                        **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                    ),
                )
            )
    elif ext in {".bat", ".cmd"}:
        attempts.append(
            (
                "cmd-file",
                lambda: Popen(
                    [os.environ.get("COMSPEC", "cmd"), "/c", str(path)],
                    stdout=None,
                    stderr=None,
                    **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                ),
            )
        )
    elif ext == ".ps1":
        attempts.append(
            (
                "ps1",
                lambda: Popen(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(path)],
                    stdout=None,
                    stderr=None,
                    **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                ),
            )
        )
    elif ext == ".sh":
        attempts.append(
            (
                "bash",
                lambda: Popen(
                    ["bash", str(path)],
                    stdout=None,
                    stderr=None,
                    **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                ),
            )
        )
        attempts.append(
            (
                "sh-file",
                lambda: Popen(
                    ["sh", str(path)],
                    stdout=None,
                    stderr=None,
                    **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                ),
            )
        )
    elif ext == ".js":
        for host in ("wscript", "cscript"):
            attempts.append(
                (
                    host,
                    lambda h=host: Popen(
                        [h, str(path)],
                        stdout=None,
                        stderr=None,
                        **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                    ),
                )
            )
        node = shutil.which("node") or shutil.which("nodejs")
        if node:
            attempts.append(
                (
                    "node",
                    lambda ne=node: Popen(
                        [ne, str(path)],
                        stdout=None,
                        stderr=None,
                        **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                    ),
                )
            )
    elif ext == ".vbs":
        attempts.append(
            (
                "cscript",
                lambda: Popen(
                    ["cscript", "//B", str(path)],
                    stdout=None,
                    stderr=None,
                    **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                ),
            )
        )
    elif ext == ".wsf":
        for host in ("wscript", "cscript"):
            attempts.append(
                (
                    host,
                    lambda h=host: Popen(
                        [h, str(path)],
                        stdout=None,
                        stderr=None,
                        **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                    ),
                )
            )
    elif ext == ".jar":
        attempts.append(
            (
                "java",
                lambda: Popen(
                    ["java", "-jar", str(path)],
                    stdout=None,
                    stderr=None,
                    **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                ),
            )
        )
        javaw = shutil.which("javaw")
        if javaw:
            attempts.append(
                (
                    "javaw",
                    lambda jw=javaw: Popen(
                        [jw, "-jar", str(path)],
                        stdout=None,
                        stderr=None,
                        **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                    ),
                )
            )
    elif ext == ".msi":
        attempts.append(
            (
                "msiexec",
                lambda: Popen(
                    ["msiexec", "/i", str(path)],
                    stdout=None,
                    stderr=None,
                    **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                ),
            )
        )
        attempts.append(
            (
                "msiexec-quiet",
                lambda: Popen(
                    ["msiexec", "/qn", "/i", str(path)],
                    stdout=None,
                    stderr=None,
                    **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                ),
            )
        )
    elif ext == ".deb":
        attempts.append(
            (
                "dpkg",
                lambda: Popen(
                    ["dpkg", "-i", str(path)],
                    stdout=None,
                    stderr=None,
                    **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                ),
            )
        )
    elif ext.lower() == ".appimage":
        attempts.append(
            (
                "appimage",
                lambda: Popen(
                    [str(path)],
                    stdout=None,
                    stderr=None,
                    **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                ),
            )
        )
        attempts.append(
            (
                "chmod-appimage",
                lambda: (security._run(["chmod", "+x", str(path)]), launch_exe(path, hidden=hidden))[1],
            )
        )
    elif ext == ".pkg":
        attempts.append(
            (
                "installer",
                lambda: Popen(
                    ["sudo", "installer", "-pkg", str(path), "-target", "/"],
                    stdout=None,
                    stderr=None,
                    **({"creationflags": hidden_creation_flags(detach=False)} if hidden else {}),
                ),
            )
        )

    attempts.append(("direct", lambda: launch_exe(path, hidden=hidden)))

    system = platform.system()
    if system == "Windows":
        attempts.append(
            (
                "cmd",
                lambda: Popen(
                    [os.environ.get("COMSPEC", "cmd"), "/c", str(path)],
                    stdout=None,
                    stderr=None,
                ),
            )
        )
        attempts.append(
            (
                "powershell",
                lambda: Popen(
                    ["powershell", "-Command", f"Start-Process -FilePath '{path}'"],
                    stdout=None,
                    stderr=None,
                ),
            )
        )
        attempts.append(
            (
                "start",
                lambda: Popen([os.environ.get("COMSPEC", "cmd"), "/c", "start", "", str(path)], stdout=None, stderr=None),
            )
        )
        attempts.append(
            (
                "shell",
                lambda: Popen(str(path), shell=True),
            )
        )
    elif system == "Darwin":
        attempts.append(
            (
                "open",
                lambda: Popen(["open", str(path)], stdout=None, stderr=None),
            )
        )
        if path.suffix == ".app" and path.is_dir():
            attempts.append(
                (
                    "open-app",
                    lambda: Popen(["open", "-a", str(path)], stdout=None, stderr=None),
                )
            )
            attempts.append(
                (
                    "open-new",
                    lambda: Popen(["open", "-n", str(path)], stdout=None, stderr=None),
                )
            )
            mac_exec = path / "Contents" / "MacOS" / path.stem
            if mac_exec.is_file():
                attempts.append(
                    (
                        "mac-direct",
                        lambda me=mac_exec: Popen([str(me)], stdout=None, stderr=None),
                    )
                )
    else:
        attempts.append(
            (
                "sh",
                lambda: Popen(["sh", str(path)], stdout=None, stderr=None),
            )
        )
        attempts.append(
            (
                "sh-c",
                lambda: Popen(["sh", "-c", str(path)], stdout=None, stderr=None),
            )
        )
        if ext == ".exe" and shutil.which("wine"):
            attempts.append(("wine", lambda: Popen(["wine", str(path)], stdout=None, stderr=None)))
        attempts.append(
            (
                "nohup",
                lambda: Popen(["nohup", str(path)], stdout=None, stderr=None),
            )
        )
        if shutil.which("xdg-open"):
            attempts.append(("xdg-open", lambda: Popen(["xdg-open", str(path)], stdout=None, stderr=None)))
        attempts.append(("shell", lambda: Popen(str(path), shell=True)))
        if shutil.which("wsl"):
            attempts.append(("wsl", lambda: Popen(["wsl", str(path)], stdout=None, stderr=None)))
            try:
                cp = subprocess.run(["wsl", "wslpath", "-a", str(path)], capture_output=True, text=True, check=False)
                if cp.returncode == 0:
                    wpath = cp.stdout.strip()
                    attempts.append(("wsl-conv", lambda: Popen(["wsl", wpath], stdout=None, stderr=None)))
            except Exception:
                pass

    if system == "Windows" and hasattr(os, "startfile"):
        def startfile_proc() -> Popen:
            os.startfile(str(path))
            class Dummy:
                def poll(self) -> None:
                    return None

            return Dummy()

        attempts.append(("startfile", startfile_proc))

    for name, func in attempts:
        try:
            return func()
        except PermissionError as exc:
            security_log.add_event("exe_test", f"permission for {name}: {exc}")
            if security.ensure_admin("Launching requires admin rights"):
                try:
                    return func()
                except Exception as exc2:
                    security_log.add_event(
                        "exe_test", f"admin launch {name} failed: {exc2}"
                    )
            continue
        except Exception as exc:
            security_log.add_event("exe_test", f"launch {name} failed: {exc}")
            continue

    if system != "Windows" and not os.access(path, os.X_OK):
        if security._run(["chmod", "+x", str(path)]):
            try:
                return launch_exe(path, hidden=hidden)
            except Exception as exc:
                security_log.add_event("exe_test", f"chmod retry failed: {exc}")

    if security.run_command_background([str(path)]):
        class Dummy:
            def poll(self) -> None:
                return None

        return Dummy()

    if security._run([str(path)]):
        class Dummy:
            def poll(self) -> None:
                return None

        return Dummy()

    try:
        spawn_detached([str(path)])
        class Dummy:
            def poll(self) -> None:
                return None

        return Dummy()
    except Exception as exc:
        security_log.add_event("exe_test", f"spawn_detached failed: {exc}")

    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stress test an executable")
    parser.add_argument("exe", help="Path to the executable to test")
    parser.add_argument(
        "-n",
        "--iterations",
        type=int,
        default=5,
        help="Number of times to run",
    )
    parser.add_argument("--ps-before", help="PowerShell command to run before each launch")
    parser.add_argument("--ps-after", help="PowerShell command to run after each launch")
    parser.add_argument(
        "-t",
        "--runtime",
        type=float,
        default=2.0,
        help="Seconds to keep running",
    )
    parser.add_argument("--hidden", action="store_true", help="Hide the executable window")
    parser.add_argument("--admin", action="store_true", help="Request admin rights first")
    parser.add_argument("--no-port-scan", action="store_true", help="Skip open port scanning")
    parser.add_argument("--refresh", type=int, default=4, help="UI refresh rate")
    parser.add_argument(
        "--cooldown", type=float, default=0.0, help="Seconds to wait after each iteration"
    )
    parser.add_argument(
        "--max-fails",
        type=int,
        default=0,
        help="Abort after this many failures (0 = unlimited)",
    )
    return parser.parse_args(argv)


async def run_cli_async(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    exe_path = Path(args.exe)
    if not exe_path.is_file():
        raise SystemExit(f"Executable not found: {exe_path}")

    if args.admin:
        try:
            security.require_admin("Administrator privileges are required")
        except PermissionError:
            return

    console = console or Console()
    console.clear()
    render_header(console)

    progress = Progress(transient=True)
    table = Table(title="Open Ports", expand=True)
    table.add_column("Iteration", justify="right")
    table.add_column("Ports")
    cpu_table = Table(title="CPU %", expand=True)
    cpu_table.add_column("Iteration", justify="right")
    cpu_table.add_column("Usage")
    mem_table = Table(title="Mem MB", expand=True)
    mem_table.add_column("Iteration", justify="right")
    mem_table.add_column("Usage")
    fail_table = Table(title="Failures", expand=True)
    fail_table.add_column("Iteration", justify="right")
    fail_table.add_column("Reason")
    event_history: list[str] = []

    if args.no_port_scan:
        baseline_ports: set[int] = set()
    else:
        baseline_ports = set((await security.async_list_open_ports()).keys())

    async def run_iteration(index: int) -> None:
        reason = None
        security_log.add_event("exe_test", f"Starting iteration {index} for {exe_path}")
        event_history.append(f"start {index}")
        if args.ps_before:
            try:
                await asyncio.to_thread(run_powershell, args.ps_before)
            except Exception as exc:
                security_log.add_event("exe_test", f"ps-before failed: {exc}")
        proc = smart_launch_exe(exe_path, hidden=args.hidden)
        if proc is None:
            security_log.add_event("exe_test", "all launch methods failed")
            return "launch"
        pmon = None
        try:
            import psutil
            pmon = psutil.Process(proc.pid)
            pmon.cpu_percent(interval=None)
        except Exception:
            pmon = None
        try:
            await asyncio.to_thread(proc.wait, timeout=args.runtime)
        except Exception:
            pass
        if proc.poll() is None:
            ok = await asyncio.to_thread(smart_terminate, proc)
            if not ok:
                security_log.add_event("exe_test", "terminate via smart_terminate failed")
                reason = "terminate"
                try:
                    await asyncio.to_thread(security.kill_process_tree, proc.pid)
                except Exception as exc:
                    security_log.add_event("exe_test", f"kill tree failed: {exc}")
        if args.ps_after:
            try:
                await asyncio.to_thread(run_powershell, args.ps_after)
            except Exception as exc:
                security_log.add_event("exe_test", f"ps-after failed: {exc}")
        if args.no_port_scan:
            ports = {}
            new_ports: set[int] = set()
        else:
            ports = await security.async_list_open_ports()
            new_ports = set(ports.keys()) - baseline_ports
        cpu_val = "-"
        mem_val = "-"
        if pmon is not None:
            try:
                cpu_val = f"{pmon.cpu_percent(interval=None):.1f}"
                mem_val = f"{pmon.memory_info().rss / (1024*1024):.1f}"
            except Exception:
                cpu_val = "err"
                mem_val = "err"
        security_log.add_event("exe_test", f"Finished iteration {index}; open ports: {list(ports.keys())}")
        event_history.append(f"end {index}")
        table.add_row(str(index), ", ".join(map(str, sorted(new_ports))) or "-")
        cpu_table.add_row(str(index), cpu_val)
        mem_table.add_row(str(index), mem_val)
        return reason

    with MatrixBorder(console=console), Live(console=console, refresh_per_second=args.refresh) as live:
        task = progress.add_task("testing", total=args.iterations, start=True)
        fails = 0
        for i in range(1, args.iterations + 1):
            reason = await run_iteration(i)
            if reason:
                fail_table.add_row(str(i), reason)
                fails += 1
            while len(event_history) > 5:
                event_history.pop(0)
            log_table = Table(title="Events", expand=True)
            log_table.add_column("Event")
            for ev in event_history:
                log_table.add_row(ev)
            progress.update(task, advance=1)
            live.update(Group(progress, table, cpu_table, mem_table, fail_table, log_table))
            if args.max_fails and fails >= args.max_fails:
                event_history.append("aborted")
                break
            if args.cooldown:
                await asyncio.sleep(args.cooldown)

    console.print(table)
    console.print(cpu_table)
    log_table = Table(title="Events", expand=True)
    log_table.add_column("Event")
    for ev in event_history:
        log_table.add_row(ev)
    console.print(mem_table)
    console.print(fail_table)
    console.print(log_table)

    counts = security_log.event_counts()
    count_table = Table(title="Log Counts", expand=True)
    count_table.add_column("Category")
    count_table.add_column("Total", justify="right")
    for cat, cnt in sorted(counts.items()):
        count_table.add_row(cat, str(cnt))
    console.print(count_table)


def run_cli(args: argparse.Namespace, *, console: Console | None = None) -> None:
    """Synchronous wrapper for :func:`run_cli_async`."""
    asyncio.run(run_cli_async(args, console=console))


def main(argv: list[str] | None = None) -> None:
    run_cli(parse_args(argv))


if __name__ == "__main__":
    main()
