#!/usr/bin/env python3
"""CoolBox — install/inspect utilities with neon border UI, atomic console, and end-of-run summary."""

from __future__ import annotations

__version__ = "1.5.1"

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Iterable, Sequence, Tuple

# ---------- rich UI ----------
try:
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import (
        Progress,
        SpinnerColumn,
        BarColumn,
        TimeElapsedColumn,
        TaskProgressColumn,
        MofNCompleteColumn,
    )
    from rich import box
except ImportError:  # pragma: no cover
    subprocess.run([sys.executable, "-m", "pip", "install", "rich>=13"], check=False)
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import (
        Progress,
        SpinnerColumn,
        BarColumn,
        TimeElapsedColumn,
        TaskProgressColumn,
        MofNCompleteColumn,
    )
    from rich import box

# ---------- project helpers ----------
try:
    from src.ensure_deps import ensure_numpy
except Exception:  # pragma: no cover
    def ensure_numpy() -> None:  # type: ignore
        pass

try:
    from src.utils.helpers import (
        log as _helper_log,
        get_system_info,
        run_with_spinner,
        console as _helper_console,
    )
except Exception:
    _helper_console = None
    def _helper_log(msg: str) -> None:  # type: ignore
        pass
    def get_system_info() -> dict:  # type: ignore
        return {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "platform": sys.platform,
            "cwd": str(Path.cwd()),
        }
    def run_with_spinner(fn, message: str):  # type: ignore
        return fn()

# Neon border + atomic console
from src.utils.rainbow import NeonPulseBorder, LockingConsole

# ---------- env + constants ----------
IS_TTY = sys.stdout.isatty()
OFFLINE = os.environ.get("COOLBOX_OFFLINE") == "1"
NO_GIT = os.environ.get("COOLBOX_NO_GIT") == "1"
NO_ANIM = (
    os.environ.get("COOLBOX_NO_ANIM") == "1"
    or os.environ.get("COOLBOX_CI") == "1"
    or os.environ.get("CI") == "1"
    or not IS_TTY
)
ALT_SCREEN = os.environ.get("COOLBOX_ALT_SCREEN", "1") == "1"

MIN_PYTHON: Tuple[int, int] = (3, 10)
if sys.version_info < MIN_PYTHON:
    raise RuntimeError(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required")

ROOT_DIR = Path(__file__).resolve().parent
VENV_DIR = ROOT_DIR / ".venv"
REQUIREMENTS_FILE = ROOT_DIR / "requirements.txt"
DEV_PACKAGES: Sequence[str] = ("pip-tools>=7", "build>=1", "wheel>=0.43", "pytest>=8")

# Default lightweight mode for downstream modules
os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")

# One console for everything, wrapped with a global lock to avoid flicker or torn output.
console = LockingConsole()
def log(msg: str) -> None:
    console.print(f"[dim]»[/] {msg}")

# ---------- summary tracking ----------
class RunSummary:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)
        log(f"[yellow]WARN[/]: {msg}")

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        log(f"[red]ERROR[/]: {msg}")

    def render(self) -> None:
        # Always show a box at the end.
        if not self.warnings and not self.errors:
            panel = Panel.fit("[green]No warnings or errors.[/]", title="Summary", box=box.ROUNDED)
            console.print(panel)
            return

        table = Table(box=box.SIMPLE_HEAVY)
        table.add_column("Type", no_wrap=True)
        table.add_column("Message", overflow="fold")
        for w in self.warnings:
            table.add_row("[yellow]Warning[/]", w)
        for e in self.errors:
            table.add_row("[red]Error[/]", e)
        console.print(Panel(table, title="Summary", box=box.ROUNDED))

SUMMARY = RunSummary()

# ---------- helpers ----------
def _run(cmd: Sequence[str], *, cwd: Path | None = None, env: dict | None = None) -> None:
    """Run a command and raise if it fails."""
    subprocess.check_call(list(cmd), cwd=cwd, env=env)


def _retry(
    cmd: Sequence[str], *, attempts: int = 3, delay: float = 0.8, cwd: Path | None = None
) -> None:
    """Retry a command a few times with exponential backoff."""
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            _run(cmd, cwd=cwd)
            return
        except Exception as e:  # pragma: no cover - exercised via tests
            last = e
            if i < attempts:
                time.sleep(delay * i)
    if last is not None:
        raise last


def locate_root(start: Path) -> Path:
    """Walk upwards from *start* looking for a requirements.txt file."""
    p = Path(start).resolve()
    for parent in (p, *p.parents):
        if (parent / "requirements.txt").exists():
            return parent
    return p


def get_root() -> Path:
    """Return project root, honoring COOLBOX_ROOT if set."""
    env = os.environ.get("COOLBOX_ROOT")
    if env:
        return Path(env)
    return locate_root(Path(__file__).resolve())


def get_venv_dir() -> Path:
    """Return virtualenv directory, honoring COOLBOX_VENV if set."""
    env = os.environ.get("COOLBOX_VENV")
    if env:
        return Path(env)
    return VENV_DIR

def _venv_python() -> str:
    if sys.platform.startswith("win"):
        py = VENV_DIR / "Scripts" / "python.exe"
    else:
        py = VENV_DIR / "bin" / "python"
    return str(py)

def ensure_venv() -> str:
    if not VENV_DIR.exists():
        log(f"Creating venv at {VENV_DIR}")
        import venv
        venv.EnvBuilder(with_pip=True, clear=False, upgrade=False).create(str(VENV_DIR))
    return _venv_python()

def _pip(
    args: Sequence[str],
    python: str | Path | None = None,
    *,
    upgrade_pip: bool = False,
    attempts: int = 2,
) -> None:
    """Run ``pip`` inside a NeonPulseBorder to provide a blue glow.

    Parameters
    ----------
    args:
        Arguments passed directly to ``pip``.
    python:
        Python interpreter to invoke. If ``None`` a virtualenv will be
        created or reused and its interpreter used.
    upgrade_pip:
        Whether to upgrade ``pip`` first.
    attempts:
        Number of retry attempts on failure.
    """

    py = str(python or ensure_venv())
    base_cmd = [py, "-m", "pip"]
    if upgrade_pip:
        _retry(base_cmd + ["install", "-U", "pip", "setuptools", "wheel"], attempts=attempts)

    cmd = base_cmd + list(args)
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            # NeonPulseBorder provides a subtle blue glow while pip runs.
            with NeonPulseBorder():
                subprocess.check_call(cmd)
            return
        except Exception as e:  # pragma: no cover - network failures etc.
            last = e
            if i < attempts:
                time.sleep(0.8 * i)
    if last is not None:
        raise last

def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()

def _stamp_path() -> Path:
    return VENV_DIR / ".req_hash"

def _should_install(req: Path, upgrade: bool) -> bool:
    if upgrade:
        return True
    if not req.exists():
        return False
    sp = _stamp_path()
    if not sp.exists():
        return True
    try:
        return sp.read_text().strip() != _file_hash(req)
    except Exception:
        return True

def _write_req_stamp(req: Path) -> None:
    _stamp_path().write_text(_file_hash(req), encoding="utf-8")

def update_repo() -> None:
    if NO_GIT or OFFLINE:
        log("Skip git update (disabled or offline).")
        return
    if not (ROOT_DIR / ".git").exists():
        log("No .git directory. Skipping update.")
        return
    log("Updating repository...")
    try:
        _retry(["git", "-C", str(ROOT_DIR), "fetch", "--all", "--tags", "--prune"], attempts=2)
        _retry(["git", "-C", str(ROOT_DIR), "pull", "--rebase", "--autostash"], attempts=2)
    except Exception as e:
        SUMMARY.add_warning(f"git update failed: {e}")

def build_extensions() -> None:
    # Optional native extras, safe to skip if not present
    try:
        py = ensure_venv()
        _run([py, "-m", "build", "--wheel", "--no-isolation"], cwd=ROOT_DIR)
    except Exception as e:
        SUMMARY.add_warning(f"native build skipped: {e}")

def check_outdated(*, requirements: Path | None, upgrade: bool = False) -> None:
    import json
    py = ensure_venv()
    cmd = [py, "-m", "pip", "list", "--outdated", "--format=json"]
    try:
        out = subprocess.check_output(cmd, text=True)
        pkgs = json.loads(out)
    except Exception as e:
        SUMMARY.add_warning(f"pip list --outdated failed: {e}")
        pkgs = []

    if upgrade and pkgs:
        with Progress(
            SpinnerColumn(),
            "[progress.description]{task.description}",
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            refresh_per_second=24,
            console=console,
            transient=True,
        ) as prog:
            t = prog.add_task("Upgrading outdated packages", total=len(pkgs))
            for item in pkgs:
                name = item.get("name")
                if name:
                    try:
                        _pip(["install", "-U", name], upgrade_pip=False, attempts=2)
                    except Exception as e:
                        SUMMARY.add_error(f"Upgrade {name} failed: {e}")
                prog.advance(t)
    else:
        table = Table(title="Outdated packages", box=box.SIMPLE_HEAVY)
        table.add_column("Name"), table.add_column("Version"), table.add_column("Latest"), table.add_column("Type")
        for p in pkgs:
            table.add_row(p.get("name",""), p.get("version",""), p.get("latest_version",""), p.get("type",""))
        console.print(table)

def show_info() -> None:
    info = get_system_info()
    table = Table(title="CoolBox — System Info", box=box.MINIMAL_DOUBLE_HEAD)
    for k, v in info.items():
        table.add_row(k, str(v))
    console.print(table)

def run_tests(extra: Sequence[str]) -> None:
    py = ensure_venv()
    try:
        _run([py, "-m", "pytest", "-q", *extra])
    except Exception as e:
        SUMMARY.add_error(f"pytest failed: {e}")

def doctor() -> None:
    problems: list[str] = []
    if OFFLINE:
        problems.append("OFFLINE set, downloads disabled.")
    if NO_GIT:
        problems.append("NO_GIT set, repo update disabled.")
    if not REQUIREMENTS_FILE.exists():
        problems.append("requirements.txt not found.")
    console.print(Panel.fit("\n".join(problems) or "No obvious problems.", title="Doctor", box=box.ROUNDED))

def lock() -> None:
    py = ensure_venv()
    try:
        _pip(["install", "-U", "pip-tools"], upgrade_pip=False)
        _run([py, "-m", "piptools", "compile", str(REQUIREMENTS_FILE), "--upgrade"])
    except Exception as e:
        SUMMARY.add_error(f"Lock failed: {e}")

def sync(lock_file: Path | None, *, upgrade: bool = False) -> None:
    py = ensure_venv()
    try:
        _pip(["install", "-U", "pip-tools"], upgrade_pip=False)
        args = [py, "-m", "piptools", "sync"]
        if lock_file:
            args.append(str(lock_file))
        if upgrade:
            _pip(["install", "-U", "-r", str(REQUIREMENTS_FILE)], upgrade_pip=False)
        _run(args)
    except Exception as e:
        SUMMARY.add_error(f"Sync failed: {e}")

def clean_pyc() -> None:
    n = 0
    for p in ROOT_DIR.rglob("*"):
        if p.is_dir() and p.name == "__pycache__":
            shutil.rmtree(p, ignore_errors=True)
            n += 1
    log(f"Removed {n} __pycache__ folders.")

def install(
    requirements: Path | None = None,
    *,
    dev: bool = False,
    upgrade: bool = False,
    skip_update: bool = False,
) -> None:
    os.chdir(ROOT_DIR)
    if not skip_update:
        update_repo()

    ensure_numpy()  # optional speedups
    py = ensure_venv()

    req_path = requirements or REQUIREMENTS_FILE
    planned: list[tuple[str, list[str], bool]] = []

    if req_path.is_file():
        if _should_install(req_path, upgrade):
            planned.append(("Install requirements", ["install", "-r", str(req_path), *( ["-U"] if upgrade else [] )], True))
        else:
            log("Requirements unchanged. Skipping install.")
    else:
        SUMMARY.add_warning(f"Requirements file missing: {req_path}")

    if dev:
        for pkg in DEV_PACKAGES:
            planned.append((f"Install {pkg}", ["install", pkg, *( ["-U"] if upgrade else [] )], False))

    # UI: progress + neon border with atomic console to prevent torn output
    border_ctx = (
        NeonPulseBorder(
            speed=0.04,                 # ~25 FPS, stable
            style="rounded",
            theme="pride",
            thickness=2,
            use_alt_screen=ALT_SCREEN,  # separate buffer for clean updates
            console=console,
        )
        if not NO_ANIM
        else nullcontext()
    )

    try:
        with border_ctx:
            if planned:
                with Progress(
                    SpinnerColumn(),
                    "[progress.description]{task.description}",
                    BarColumn(),
                    TaskProgressColumn(),
                    MofNCompleteColumn(),
                    TimeElapsedColumn(),
                    refresh_per_second=24,     # throttled, smooth
                    console=console,           # locked console prevents flicker
                    transient=True,
                ) as prog:
                    t = prog.add_task("Executing install plan", total=len(planned))
                    for title, pip_args, upgrade_pip in planned:
                        prog.update(t, description=title)
                        try:
                            _pip(pip_args, upgrade_pip=upgrade_pip, attempts=3)
                        except Exception as e:
                            SUMMARY.add_error(f"{title} failed: {e}")
                        prog.advance(t)

            # Verify graph
            try:
                _retry([py, "-m", "pip", "check"], attempts=1)
            except Exception as exc:
                SUMMARY.add_warning(f"pip check reported issues: {exc}")

            # Optional native build
            build_extensions()
    finally:
        # Always print final summary box
        SUMMARY.render()

    if req_path.is_file():
        try:
            _write_req_stamp(req_path)
        except Exception as e:
            SUMMARY.add_warning(f"Could not write requirement stamp: {e}")

    log("Done.")

# ---------- CLI ----------
def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="coolbox-setup", description="Install and inspect CoolBox deps.")
    sub = p.add_subparsers(dest="command", required=False)

    p_install = sub.add_parser("install", help="Install requirements and dev extras")
    p_install.add_argument("--requirements", type=Path, default=None)
    p_install.add_argument("--dev", action="store_true")
    p_install.add_argument("--upgrade", action="store_true")
    p_install.add_argument("--skip-update", action="store_true")

    sub.add_parser("info", help="Show system info")
    sub.add_parser("doctor", help="Run quick diagnostics")

    p_check = sub.add_parser("check", help="List outdated packages")
    p_check.add_argument("--requirements", type=Path, default=None)

    p_up = sub.add_parser("upgrade", help="Upgrade all outdated packages")
    p_up.add_argument("--upgrade", action="store_true", default=True)

    p_lock = sub.add_parser("lock", help="Generate lock file with pip-tools")
    p_sync = sub.add_parser("sync", help="Sync environment from lock file")
    p_sync.add_argument("--lock-file", type=Path, default=None)
    p_sync.add_argument("--upgrade", action="store_true")

    p_venv = sub.add_parser("venv", help="Create or recreate venv")
    p_venv.add_argument("--recreate", action="store_true")

    sub.add_parser("clean-pyc", help="Remove __pycache__ folders")

    p_test = sub.add_parser("test", help="Run pytest")
    p_test.add_argument("extra", nargs="*", default=[])

    sub.add_parser("update", help="git fetch/pull if repo")

    p.set_defaults(command="install")
    return p.parse_args(argv)

def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv or sys.argv[1:])
    cmd = args.command

    if cmd == "install":
        install(
            requirements=getattr(args, "requirements", None),
            dev=getattr(args, "dev", False),
            upgrade=getattr(args, "upgrade", False),
            skip_update=getattr(args, "skip_update", False),
        )
    elif cmd == "check":
        check_outdated(requirements=args.requirements)
    elif cmd == "upgrade":
        check_outdated(requirements=None, upgrade=True)
    elif cmd == "info":
        show_info()
    elif cmd == "venv":
        if getattr(args, "recreate", False) and VENV_DIR.exists():
            shutil.rmtree(VENV_DIR, ignore_errors=True)
            log("Virtualenv removed.")
        ensure_venv()
        log("Virtualenv ready.")
        SUMMARY.render()
    elif cmd == "clean-pyc":
        clean_pyc()
        SUMMARY.render()
    elif cmd == "test":
        run_tests(args.extra)
        SUMMARY.render()
    elif cmd == "update":
        update_repo()
        SUMMARY.render()
    elif cmd == "doctor":
        doctor()
        SUMMARY.render()
    elif cmd == "lock":
        lock()
        SUMMARY.render()
    elif cmd == "sync":
        sync(args.lock_file, upgrade=args.upgrade)
        SUMMARY.render()
    else:
        install()

if __name__ == "__main__":
    main()

