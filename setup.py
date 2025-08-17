#!/usr/bin/env python3
"""CoolBox — install/inspect utilities with neon border UI, atomic console, and end-of-run summary.

Changes:
- Removed border during subprocess work by default. Enable with --border or COOLBOX_BORDER=1.
- Progress + panels use the underlying Rich Console (no wrapper quirks).
- LockingConsole now fully context-manager compatible and exposes .raw for Rich internals.
- Non-interactive subprocess env to avoid stalls.
"""

from __future__ import annotations

__version__ = "1.5.6"

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Sequence, Tuple

# ---------- rich UI ----------
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import (
        Progress,
        BarColumn,
        TimeElapsedColumn,
        TaskProgressColumn,
        MofNCompleteColumn,
        ProgressColumn,
    )
    from rich.text import Text
    from rich import box
    from rich.traceback import install as _rich_tb_install
    _rich_tb_install(show_locals=False)
except ImportError:  # pragma: no cover
    subprocess.run([sys.executable, "-m", "pip", "install", "rich>=13"], check=False)
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import (
        Progress,
        BarColumn,
        TimeElapsedColumn,
        TaskProgressColumn,
        MofNCompleteColumn,
        ProgressColumn,
    )
    from rich.text import Text
    from rich import box

# ---------- optional project helpers ----------
try:
    from src.ensure_deps import ensure_numpy  # type: ignore
except Exception:  # pragma: no cover
    def ensure_numpy() -> None:  # type: ignore
        pass

try:
    from src.utils.helpers import (  # type: ignore
        get_system_info,
        console as _helper_console,
    )
except Exception:
    _helper_console = None

    def get_system_info() -> dict:  # type: ignore
        return {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "platform": sys.platform,
            "cwd": str(Path.cwd()),
        }

# ---------- neon border fallback ----------
class _NoopBorder:
    def __init__(self, *_, **__): ...
    def __enter__(self): return self
    def __exit__(self, *_): return False

try:
    from src.utils.rainbow import NeonPulseBorder as _BorderImpl  # type: ignore
except Exception:
    _BorderImpl = _NoopBorder  # type: ignore

def NeonPulseBorder(**kwargs):
    return _BorderImpl(**kwargs)

# ---------- rainbow helpers ----------

RAINBOW_COLORS: Sequence[str] = (
    "#e40303",
    "#ff8c00",
    "#ffed00",
    "#008026",
    "#004dff",
    "#750787",
)


class RainbowSpinnerColumn(ProgressColumn):
    """Spinner that cycles through a rainbow of colors."""

    def __init__(self, frames: str = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", colors: Sequence[str] | None = None):
        self.frames = frames
        self.colors = list(colors or RAINBOW_COLORS)
        self._index = 0

    def render(self, task):  # type: ignore[override]
        char = self.frames[self._index % len(self.frames)]
        color = self.colors[self._index % len(self.colors)]
        self._index += 1
        return Text(char, style=color)


def rainbow_text(msg: str, colors: Sequence[str] | None = None) -> Text:
    """Return Text with a simple rainbow gradient."""
    colors = list(colors or RAINBOW_COLORS)
    t = Text()
    for i, ch in enumerate(msg):
        t.append(ch, style=colors[i % len(colors)])
    return t

# ---------- atomic console ----------
class LockingConsole:
    """Thread-safe console wrapper compatible with Rich. Exposes .raw for internals."""
    def __init__(self, base: Console | None = None):
        self._lock = threading.RLock()
        self._console = base or Console(soft_wrap=False, highlight=False)

    # Context manager support
    def __enter__(self):
        enter = getattr(self._console, "__enter__", None)
        if callable(enter):
            enter()
        return self

    def __exit__(self, exc_type, exc, tb):
        exit_ = getattr(self._console, "__exit__", None)
        if callable(exit_):
            return exit_(exc_type, exc, tb)
        return False

    def print(self, *args, **kwargs):
        with self._lock:
            self._console.print(*args, **kwargs)

    def log(self, *args, **kwargs):
        with self._lock:
            self._console.log(*args, **kwargs)

    def flush(self):
        with self._lock:
            try:
                self._console.file.flush()
            except Exception:
                pass

    @property
    def raw(self) -> Console:
        """Underlying Rich Console for constructs that expect a real Console."""
        return self._console

    def __getattr__(self, name):
        return getattr(self._console, name)

# ---------- env + constants ----------
IS_TTY = sys.stdout.isatty()
OFFLINE = os.environ.get("COOLBOX_OFFLINE") == "1"
NO_GIT = os.environ.get("COOLBOX_NO_GIT") == "1"

CLI_NO_ANIM = os.environ.get("COOLBOX_FORCE_NO_ANIM") == "1"
NO_ANIM = (
    CLI_NO_ANIM
    or os.environ.get("COOLBOX_NO_ANIM") == "1"
    or os.environ.get("COOLBOX_CI") == "1"
    or os.environ.get("CI") == "1"
    or not IS_TTY
)

# Border enabled on interactive terminals unless explicitly disabled.
_border_env = os.environ.get("COOLBOX_BORDER")
if _border_env is None:
    BORDER_ENABLED_DEFAULT = IS_TTY
else:
    BORDER_ENABLED_DEFAULT = _border_env == "1"

ALT_SCREEN = False  # keep false; alt-screens + subprocess output can wedge terminals

MIN_PYTHON: Tuple[int, int] = (3, 10)
if sys.version_info < MIN_PYTHON:
    raise RuntimeError(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required")

def locate_root(start: Path) -> Path:
    """Locate project root by walking parents for common markers."""
    p = Path(start).resolve()
    markers = {"requirements.txt", "pyproject.toml", ".git"}
    for parent in (p, *p.parents):
        if any((parent / m).exists() for m in markers):
            return parent
    return p

def get_root() -> Path:
    env = os.environ.get("COOLBOX_ROOT")
    if env:
        return Path(env).resolve()
    return locate_root(Path(__file__).resolve())

def get_venv_dir() -> Path:
    env = os.environ.get("COOLBOX_VENV")
    if env:
        return Path(env).resolve()
    return get_root() / ".venv"

ROOT_DIR = get_root()
REQUIREMENTS_FILE = ROOT_DIR / "requirements.txt"
DEV_PACKAGES: Sequence[str] = ("pip-tools>=7", "build>=1", "wheel>=0.43", "pytest>=8")

# default lightweight mode
os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")

# Non-interactive env defaults. Our keys override OS env.
BASE_ENV = {
    **os.environ,
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_NO_INPUT": "1",
    "PYTHONUNBUFFERED": "1",
    "GIT_TERMINAL_PROMPT": "0",
}

# One global console
console = LockingConsole(_helper_console or Console(soft_wrap=False, highlight=False))

def log(msg: str) -> None:
    console.print(f"[dim]»[/] {msg}")


def show_setup_banner() -> None:
    """Display a fancy rainbow setup banner for CoolBox."""
    banner = rainbow_text(f" CoolBox setup v{__version__} ")
    path = Text(str(ROOT_DIR), style="bold magenta")
    content = Text.assemble(banner, "\n", path)
    console.print(Panel(content, box=box.ROUNDED, expand=False))


def check_python_version() -> None:
    """Verify the current Python version meets requirements."""
    if sys.version_info < MIN_PYTHON:
        raise RuntimeError(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required"
        )

# ---------- summary ----------
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
def _venv_python() -> str:
    venv_dir = get_venv_dir()
    py = venv_dir / ("Scripts/python.exe" if sys.platform.startswith("win") else "bin/python")
    return str(py)

def ensure_venv() -> str:
    venv_dir = get_venv_dir()
    if not venv_dir.exists():
        log(f"Creating venv at {venv_dir}")
        import venv as _venv
        _venv.EnvBuilder(with_pip=True, clear=False, upgrade=False).create(str(venv_dir))
    return _venv_python()

def _run(cmd: Sequence[str], *, cwd: Path | None = None, env: dict | None = None) -> None:
    """Run command in non-interactive mode. Inherit IO for live display."""
    final_env = dict(BASE_ENV)
    if env:
        final_env.update(env)
    res = subprocess.run(list(cmd), cwd=cwd, env=final_env)
    if res.returncode != 0:
        raise subprocess.CalledProcessError(res.returncode, cmd)

def _retry(cmd: Sequence[str], *, attempts: int = 3, delay: float = 0.8, cwd: Path | None = None) -> None:
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            _run(cmd, cwd=cwd)
            return
        except Exception as e:  # pragma: no cover
            last = e
            if i < attempts:
                time.sleep(delay * i)
    if last is not None:
        raise last

def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()

def _stamp_path() -> Path:
    return get_venv_dir() / ".req_hash"

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
    try:
        py = ensure_venv()
        _run([py, "-m", "build", "--wheel", "--no-isolation"], cwd=ROOT_DIR)
    except Exception as e:
        SUMMARY.add_warning(f"native build skipped: {e}")

def _progress(**overrides):
    """Progress configured for safety on all terminals."""
    return Progress(
        RainbowSpinnerColumn(),
        "[progress.description]{task.description}",
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        refresh_per_second=12,
        console=console.raw,          # use real Console
        transient=True,
        disable=NO_ANIM,              # auto-disable when not TTY or CI
        **overrides,
    )

def _pip(
    args: Sequence[str],
    python: str | Path | None = None,
    *,
    upgrade_pip: bool = False,
    attempts: int = 2,
) -> None:
    """Run pip with retries. No border by default to avoid UI deadlocks."""
    py = str(python or ensure_venv())
    base_cmd = [py, "-m", "pip"]

    if OFFLINE:
        SUMMARY.add_warning(
            "Offline mode: skipping " + " ".join(base_cmd + list(args))
        )
        return

    if upgrade_pip:
        _retry(base_cmd + ["install", "-U", "pip", "setuptools", "wheel"], attempts=attempts)
    cmd = base_cmd + list(args)

    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            _run(cmd)  # live output, non-interactive env, no prompts
            return
        except Exception as e:  # pragma: no cover
            last = e
            if i < attempts:
                time.sleep(0.8 * i)
    if last is not None:
        raise last

def check_outdated(*, requirements: Path | None, upgrade: bool = False) -> None:
    import json
    py = ensure_venv()
    cmd = [py, "-m", "pip", "list", "--outdated", "--format=json"]
    try:
        out = subprocess.check_output(cmd, text=True, env=BASE_ENV)
        pkgs = json.loads(out)
    except Exception as e:
        SUMMARY.add_warning(f"pip list --outdated failed: {e}")
        pkgs = []

    if upgrade and pkgs:
        with _progress() as prog:
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
        table.add_column("Name")
        table.add_column("Version")
        table.add_column("Latest")
        table.add_column("Type")
        for p in pkgs:
            table.add_row(p.get("name", ""), p.get("version", ""), p.get("latest_version", ""), p.get("type", ""))
        console.print(table)

def show_info() -> None:
    info = get_system_info()
    table = Table(title="CoolBox — System Info", box=box.MINIMAL_DOUBLE_HEAD)
    for k, v in info.items():
        table.add_row(k, str(v))
    console.print(table)

def run_tests(extra: Sequence[str]) -> None:
    py = ensure_venv()
    with _progress() as prog:
        prog.add_task("Running tests")
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
    no_anim: bool | None = None,
    border: bool | None = None,
) -> None:
    os.chdir(ROOT_DIR)
    if not skip_update:
        update_repo()

    ensure_numpy()
    py = ensure_venv()

    # runtime toggles
    global NO_ANIM
    if no_anim is True:
        NO_ANIM = True
    border_enabled = BORDER_ENABLED_DEFAULT if border is None else bool(border)
    if NO_ANIM:
        border_enabled = False

    req_path = requirements or REQUIREMENTS_FILE
    planned: list[tuple[str, list[str], bool]] = []

    if req_path.is_file():
        if _should_install(req_path, upgrade):
            args = ["install", "-r", str(req_path)]
            if upgrade:
                args.append("-U")
            planned.append(("Install requirements", args, True))
        else:
            log("Requirements unchanged. Skipping install.")
    else:
        SUMMARY.add_warning(f"Requirements file missing: {req_path}")

    if dev:
        dev_req = ROOT_DIR / "requirements-dev.txt"
        if dev_req.is_file():
            args = ["install", "-r", str(dev_req)]
            if upgrade:
                args.append("-U")
            planned.append(("Install dev requirements", args, True))
        else:
            for pkg in DEV_PACKAGES:
                args = ["install", pkg]
                if upgrade:
                    args.append("-U")
                planned.append((f"Install {pkg}", args, False))

    border_ctx = (
        NeonPulseBorder(
            speed=0.04,
            style="rounded",
            theme="pride",
            thickness=2,
            use_alt_screen=ALT_SCREEN,
            console=console.raw,    # pass real Console
        )
        if border_enabled
        else nullcontext()
    )

    try:
        with border_ctx:
            show_setup_banner()
            if planned:
                with _progress() as prog:
                    t = prog.add_task("Executing install plan", total=len(planned))
                    for title, pip_args, upgrade_pip in planned:
                        prog.update(t, description=title)
                        try:
                            _pip(pip_args, upgrade_pip=upgrade_pip, attempts=3)
                        except Exception as e:
                            SUMMARY.add_error(f"{title} failed: {e}")
                        prog.advance(t)

            try:
                _retry([py, "-m", "pip", "check"], attempts=1)
            except Exception as exc:
                SUMMARY.add_warning(f"pip check reported issues: {exc}")

            build_extensions()
    finally:
        console.flush()
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
    p_install.add_argument("--no-anim", action="store_true", help="Disable animations for this run")
    p_install.add_argument("--border", action="store_true", help="Enable neon border UI")

    sub.add_parser("info", help="Show system info")
    sub.add_parser("doctor", help="Run quick diagnostics")

    p_check = sub.add_parser("check", help="List outdated packages")
    p_check.add_argument("--requirements", type=Path, default=None)

    p_up = sub.add_parser("upgrade", help="Upgrade all outdated packages")
    p_up.add_argument("--upgrade", action="store_true", default=True)

    sub.add_parser("lock", help="Generate lock file with pip-tools")
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

    try:
        if cmd == "install":
            install(
                requirements=getattr(args, "requirements", None),
                dev=getattr(args, "dev", False),
                upgrade=getattr(args, "upgrade", False),
                skip_update=getattr(args, "skip_update", False),
                no_anim=getattr(args, "no_anim", False),
                border=getattr(args, "border", None),
            )
        elif cmd == "check":
            check_outdated(requirements=args.requirements)
            SUMMARY.render()
        elif cmd == "upgrade":
            check_outdated(requirements=None, upgrade=True)
            SUMMARY.render()
        elif cmd == "info":
            show_info()
            SUMMARY.render()
        elif cmd == "venv":
            if getattr(args, "recreate", False):
                vdir = get_venv_dir()
                if vdir.exists():
                    shutil.rmtree(vdir, ignore_errors=True)
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
    except KeyboardInterrupt:
        SUMMARY.add_warning("Interrupted by user.")
        SUMMARY.render()
        sys.exit(130)
    except BaseException as e:
        SUMMARY.add_error(f"Fatal: {e.__class__.__name__}: {e}")
        SUMMARY.render()
        raise

if __name__ == "__main__":
    main()
