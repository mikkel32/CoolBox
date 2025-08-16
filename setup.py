"""Utility helpers for installing and inspecting CoolBox dependencies."""

from __future__ import annotations

__version__ = "1.4.0"

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Iterable

try:
    from rich.text import Text
    from rich.progress import (
        Progress,
        SpinnerColumn,
        BarColumn,
        TimeElapsedColumn,
        TaskProgressColumn,
        MofNCompleteColumn,
    )
    from rich.console import Console, Control
    from rich.table import Table
    from rich.panel import Panel
    from rich import box
except ImportError:  # pragma: no cover
    from src.ensure_deps import ensure_rich

    ensure_rich()
    from rich.text import Text
    from rich.progress import (
        Progress,
        SpinnerColumn,
        BarColumn,
        TimeElapsedColumn,
        TaskProgressColumn,
        MofNCompleteColumn,
    )
    from rich.console import Console, Control
    from rich.table import Table
    from rich.panel import Panel
    from rich import box

from src.ensure_deps import ensure_numpy
from src.utils.helpers import (
    log,
    get_system_info,
    run_with_spinner,
    console,
)

# Optional speedups
try:
    ensure_numpy()
except Exception:  # pragma: no cover
    pass

# Behavior toggles
IS_TTY = sys.stdout.isatty()
NO_ANIM = (
    os.environ.get("COOLBOX_NO_ANIM") == "1"
    or os.environ.get("COOLBOX_CI") == "1"
    or os.environ.get("CI") == "1"
    or not IS_TTY
)
OFFLINE = os.environ.get("COOLBOX_OFFLINE") == "1"
NO_GIT = os.environ.get("COOLBOX_NO_GIT") == "1"

os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")  # noqa: E402

from src.utils.rainbow import NeonPulseBorder  # noqa: E402


MIN_PYTHON = (3, 10)

COOLBOX_ART = r"""
  ____            _ ____
 / ___|___   ___ | | __ )  _____  __
| |   / _ \ / _ \| |  _ \ / _ \ \/ /
| |__| (_) | (_) | | |_) | (_) >  <
 \____\___/ \___/|_|____/ \___/_/\_\
""".strip("\n")


# ---------- color helpers ----------
def _blend(c1: str, c2: str, t: float) -> str:
    c1 = c1.lstrip("#")
    c2 = c2.lstrip("#")
    if len(c1) == 3:
        c1 = "".join(ch * 2 for ch in c1)
    if len(c2) == 3:
        c2 = "".join(ch * 2 for ch in c2)
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _gradient_line(line: str, offset: float = 0.0) -> Text:
    base_a = "#00eaff"
    base_b = "#ff00d0"
    gloss_w = max(3, len(line) // 6)
    sweep = int((offset * 1.5) % (len(line) + gloss_w))

    text = Text()
    n = max(len(line) - 1, 1)
    for i, ch in enumerate(line):
        pos = (i + offset) / n
        color = _blend(base_a, base_b, (pos % 1.0))
        if sweep - gloss_w <= i <= sweep:
            k = (i - (sweep - gloss_w)) / max(1, gloss_w)
            color = _blend(color, "#ffffff", 0.65 * (1.0 - (k - 0.5) ** 2) * 1.5)
        text.append(ch, style=color)
    return text


# ---------- banner ----------
def _render_centered_ascii(lines: list[Text]) -> None:
    width, height = console.size
    content_h = len(lines)
    start_row = max(1, (height // 2) - (content_h // 2))
    max_w = min(width - 2, max((len(l.plain) for l in lines), default=0))
    for j, t in enumerate(lines):
        y = start_row + j
        x = max(1, (width // 2) - (len(t.plain) // 2))
        console.control(Control.move_to(max(0, x - 2), y))
        console.print(" " * (max_w + 4), end="")
        console.control(Control.move_to(x, y))
        console.print(t, end="")
    console.file.flush()


def show_setup_banner() -> None:
    if NO_ANIM:
        console.print(Panel.fit(Text(COOLBOX_ART), style="cyan", border_style="cyan"))
        console.rule("[bold cyan]CoolBox Setup")
        return

    console.clear()
    art_lines = COOLBOX_ART.splitlines()

    with NeonPulseBorder(speed=0.032):
        frames = 54
        import math

        for f in range(frames):
            phase = f / 8.0
            rendered: list[Text] = []
            for idx, raw in enumerate(art_lines):
                wobble = 0.75 * math.sin(phase + idx * 0.6)
                rendered.append(_gradient_line(raw, offset=phase * 2.0 + wobble))
            _render_centered_ascii(rendered)
            time.sleep(1 / 60)

    with Progress(
        SpinnerColumn(style="bold magenta"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Initializing", total=150)
        for _ in range(150):
            progress.update(task, advance=1)
            time.sleep(0.0075)

    console.rule("[bold cyan]CoolBox Setup")


# ---------- core ops ----------
def check_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        sys.exit(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer required.")


def locate_root(start: Path | None = None) -> Path:
    start = (start or Path(__file__)).resolve()
    if start.is_file():
        start = start.parent
    for path in [start, *start.parents]:
        if (path / ".git").is_dir() or (path / "requirements.txt").is_file():
            return path
    return start


def _req_hash(path: Path) -> str:
    if not path.is_file():
        return ""
    # normalize: drop comments and extras whitespace
    lines = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    data = ("\n".join(lines)).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _write_req_stamp(venv_dir: Path, h: str) -> None:
    stamp = venv_dir / ".req.hash"
    try:
        stamp.write_text(h, encoding="utf-8")
    except Exception:
        pass


def _read_req_stamp(venv_dir: Path) -> str:
    try:
        return (venv_dir / ".req.hash").read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def update_repo() -> None:
    os.chdir(ROOT_DIR)
    if NO_GIT or not (ROOT_DIR / ".git").is_dir():
        if not NO_GIT:
            log("No git repository found; skipping update check.")
        return
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
        ).strip()
        upstream = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            text=True,
        ).strip()
        remote, remote_branch = upstream.split("/", 1)
        with (nullcontext() if NO_ANIM else NeonPulseBorder(speed=0.04)):
            run_with_spinner(["git", "fetch", remote], message="Fetching updates")

        ahead_behind = subprocess.check_output(
            [
                "git",
                "rev-list",
                "--left-right",
                "--count",
                f"{branch}...{remote}/{remote_branch}",
            ],
            text=True,
        ).strip()
        ahead, behind = map(int, ahead_behind.split())
        if behind:
            log(f"Behind upstream by {behind} commit(s); pulling...")
            with (nullcontext() if NO_ANIM else NeonPulseBorder(speed=0.04)):
                run_with_spinner(
                    ["git", "pull", "--ff-only", remote, remote_branch],
                    message="Pulling updates",
                )
            log("Repository updated.")
        else:
            log("Repository is up to date.")
    except Exception as exc:
        log(f"Failed to update repository: {exc}")


def get_root() -> Path:
    env = os.environ.get("COOLBOX_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path(__file__).resolve().parent,
            text=True,
        ).strip()
        return Path(out)
    except Exception:
        return locate_root()


ROOT_DIR = get_root()
STATE_DIR = ROOT_DIR / ".coolbox"
STATE_DIR.mkdir(exist_ok=True)


def get_venv_dir() -> Path:
    env = os.environ.get("COOLBOX_VENV")
    if env:
        return Path(env).expanduser().resolve()
    return ROOT_DIR / ".venv"


REQUIREMENTS_FILE = ROOT_DIR / "requirements.txt"
VENV_DIR = get_venv_dir()
DEV_PACKAGES = ["debugpy", "flake8"]


def build_extensions() -> None:
    try:
        import importlib

        cython_build = importlib.import_module("Cython.Build")
        cythonize = cython_build.cythonize
        from setuptools import Extension
        import numpy
    except Exception as exc:  # pragma: no cover
        log(f"Skipping Cython build: {exc}")
        return
    try:
        cythonize(
            [
                Extension(
                    "src.utils._heatmap",
                    ["src/utils/_heatmap.pyx"],
                    include_dirs=[numpy.get_include()],
                ),
                Extension(
                    "src.utils._score_samples",
                    ["src/utils/_score_samples.pyx"],
                ),
            ],
            quiet=True,
        )
        log("Built optional Cython extensions.")
    except Exception as exc:  # pragma: no cover
        log(f"Failed to build Cython extensions: {exc}")


def ensure_venv(venv_dir: Path = VENV_DIR, *, python: str | None = None) -> Path:
    if sys.prefix != sys.base_prefix:
        return Path(sys.executable)

    if not venv_dir.exists():
        py_exe = python or sys.executable
        log(f"Creating virtual environment at {venv_dir} using {py_exe}")
        with (nullcontext() if NO_ANIM else NeonPulseBorder(speed=0.04)):
            run_with_spinner([py_exe, "-m", "venv", str(venv_dir)], message="Creating virtualenv")

    python_path = venv_dir / "bin" / "python"
    if not python_path.exists():  # Windows
        python_path = venv_dir / "Scripts" / "python.exe"
    return python_path


def _retry(cmd: list[str], *, attempts: int = 3, message: str = "Working") -> None:
    delay = 1.0
    for i in range(1, attempts + 1):
        try:
            with NeonPulseBorder():
                run_with_spinner(cmd, message=message)
            return
        except subprocess.CalledProcessError as exc:
            if i == attempts:
                raise
            log(f"{message} failed (try {i}/{attempts}): {exc}. Retrying in {delay:.1f}s")
            time.sleep(delay)
            delay *= 2


def _pip(
    args: Iterable[str],
    python: Path | None = None,
    *,
    upgrade_pip: bool = False,
    attempts: int = 3,
) -> None:
    py = python or ensure_venv()
    pip_cmd = [str(py), "-m", "pip"]

    # Offline and index config
    cmd = [*pip_cmd, *args]
    if OFFLINE:
        wheelhouse = ROOT_DIR / "wheels"
        if wheelhouse.is_dir():
            cmd = [*pip_cmd, "install", "--no-index", "--find-links", str(wheelhouse), *args]
        else:
            log("COOLBOX_OFFLINE=1 but wheels/ not found; proceeding online.")

    if upgrade_pip:
        _retry([*pip_cmd, "install", "--upgrade", "pip"], attempts=attempts, message="Upgrading pip")

    log("Running: " + " ".join(cmd))
    _retry(cmd, attempts=attempts, message="Installing dependencies")


def _should_install(req: Path, upgrade: bool) -> bool:
    if upgrade:
        return True
    h = _req_hash(req)
    prev = _read_req_stamp(VENV_DIR)
    return h != prev


def run_tests(extra: Iterable[str] | None = None) -> None:
    python = ensure_venv()
    cmd = [str(python), "-m", "pytest", "-q"]
    if extra:
        cmd.extend(extra)
    log("Running: " + " ".join(cmd))
    subprocess.check_call(cmd)


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

    py = ensure_venv()
    req_path = requirements or REQUIREMENTS_FILE

    steps = []

    if req_path.is_file():
        if _should_install(req_path, upgrade):
            steps.append(("Install requirements", ["install", "-r", str(req_path), *("--upgrade" if upgrade else [])], True))
        else:
            log("Requirements unchanged. Skipping install.")
    else:
        log(f"Requirements file {req_path} not found")

    if dev:
        for pkg in DEV_PACKAGES:
            steps.append((f"Install {pkg}", ["install", pkg, *("--upgrade" if upgrade else [])], False))

    # Execute steps
    for title, args, upgrade_pip in steps:
        _pip(args, python=py, upgrade_pip=upgrade_pip, attempts=3)

    # Health checks
    try:
        _retry([str(py), "-m", "pip", "check"], attempts=1, message="Verifying dependency graph")
    except Exception as exc:
        log(f"pip check reported issues: {exc}")

    # Build native extras
    build_extensions()

    # Write requirement stamp
    if req_path.is_file():
        _write_req_stamp(VENV_DIR, _req_hash(req_path))

    log("Dependencies installed.")


def check_outdated(requirements: Path | None = None, *, upgrade: bool = False) -> None:
    os.chdir(ROOT_DIR)
    req_path = requirements or REQUIREMENTS_FILE
    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        pkgs = [
            f"{p['name']} {p['version']} -> {p['latest_version']}"
            for p in __import__("json").loads(result.stdout)
        ]
    except Exception:
        pkgs = []
    if pkgs:
        log("Packages with updates available:\n" + "\n".join(pkgs))
        if upgrade:
            log("Upgrading packages...")
            names = [p.split()[0] for p in pkgs]
            _pip(["install", "--upgrade", *names])
    else:
        log("All packages up to date.")


def show_info() -> None:
    print(f"Project Root: {ROOT_DIR}")
    print(f"Virtualenv: {VENV_DIR}")
    print(get_system_info())


# ---------- smart utilities ----------
def doctor() -> None:
    """Environment diagnostics."""
    tbl = Table(title="CoolBox Doctor", box=box.SIMPLE_HEAVY)
    tbl.add_column("Check", style="bold")
    tbl.add_column("Result")
    ok = ":white_check_mark:"
    warn = ":warning:"

    # Python
    py_ok = sys.version_info >= MIN_PYTHON
    tbl.add_row("Python version", f"{ok if py_ok else warn} {sys.version.split()[0]}")

    # Venv
    py_path = ensure_venv()
    tbl.add_row("Virtualenv", f"{ok} {py_path}")

    # TTY / CI
    tbl.add_row("Interactive TTY", f"{ok if IS_TTY else warn} {IS_TTY}")
    tbl.add_row("Animations", "disabled" if NO_ANIM else "enabled")

    # Git
    has_git = (ROOT_DIR / ".git").is_dir()
    tbl.add_row("Git repo", f"{ok if has_git else warn} {has_git}")

    # Offline
    tbl.add_row("Offline mode", "ON" if OFFLINE else "OFF")

    # Pip reachability (best effort)
    reach = "skipped (offline)" if OFFLINE else "unknown"
    if not OFFLINE:
        import urllib.request

        try:
            with urllib.request.urlopen("https://pypi.org/simple/", timeout=3) as r:
                reach = f"HTTP {getattr(r, 'status', 200)}"
        except Exception as exc:
            reach = f"error: {exc!s}"
    tbl.add_row("PyPI", reach)

    console.print(tbl)


def lock(requirements_out: Path | None = None) -> None:
    """Freeze env to requirements.lock in project root."""
    py = ensure_venv()
    out = requirements_out or (ROOT_DIR / "requirements.lock")
    cmd = [str(py), "-m", "pip", "freeze", "--local"]
    txt = subprocess.check_output(cmd, text=True)
    out.write_text(txt, encoding="utf-8")
    log(f"Wrote {out}")


def sync(lock_file: Path | None = None, *, upgrade: bool = False) -> None:
    """Sync env to requirements.lock if present."""
    py = ensure_venv()
    lf = lock_file or (ROOT_DIR / "requirements.lock")
    if not lf.is_file():
        log(f"No lock file at {lf}")
        return
    args = ["install", "-r", str(lf)]
    if upgrade:
        args.append("--upgrade")
    _pip(args, python=py, upgrade_pip=upgrade)


def clean_pyc(target: Path | None = None) -> None:
    """Remove __pycache__ and *.pyc under target or repo root."""
    root = (target or ROOT_DIR).resolve()
    count = 0
    for p in root.rglob("*"):
        try:
            if p.is_dir() and p.name == "__pycache__":
                shutil.rmtree(p, ignore_errors=True)
                count += 1
            elif p.is_file() and p.suffix == ".pyc":
                p.unlink(missing_ok=True)
        except Exception:
            pass
    log(f"Cleaned {count} __pycache__ directories.")


# ---------- CLI ----------
if __name__ == "__main__":
    show_setup_banner()
    if sys.version_info < MIN_PYTHON:
        check_python_version()

    parser = argparse.ArgumentParser(description="Manage CoolBox dependencies and environment")
    sub = parser.add_subparsers(dest="command")

    install_p = sub.add_parser("install", help="Install required packages")
    install_p.add_argument("--requirements", type=Path, help="Alternate requirements file")
    install_p.add_argument("--dev", action="store_true", help="Install development packages")
    install_p.add_argument("--upgrade", action="store_true", help="Upgrade packages to latest")
    install_p.add_argument("--skip-update", action="store_true", help="Skip git update")

    sub.add_parser("info", help="Show system information")

    check_p = sub.add_parser("check", help="List outdated packages")
    check_p.add_argument("--requirements", type=Path, help="Path to the requirements file")

    sub.add_parser("update", help="Pull the latest changes from the repository")
    sub.add_parser("upgrade", help="Upgrade all outdated packages")
    sub.add_parser("doctor", help="Run environment diagnostics")
    sub.add_parser("lock", help="Freeze environment to requirements.lock")
    sync_p = sub.add_parser("sync", help="Sync environment from requirements.lock")
    sync_p.add_argument("--lock-file", type=Path, default=None)
    sync_p.add_argument("--upgrade", action="store_true")
    venv_p = sub.add_parser("venv", help="Create or ensure the project virtualenv")
    venv_p.add_argument("--recreate", action="store_true", help="Recreate the virtual environment")
    sub.add_parser("clean", help="Remove the project virtualenv")
    sub.add_parser("clean-pyc", help="Remove __pycache__ and *.pyc")
    test_p = sub.add_parser("test", help="Run the test suite")
    test_p.add_argument("extra", nargs="*", help="Additional pytest arguments")

    args = parser.parse_args()

    if args.command == "check":
        check_outdated(requirements=args.requirements)
    elif args.command == "upgrade":
        check_outdated(requirements=None, upgrade=True)
    elif args.command == "info":
        show_info()
    elif args.command == "venv":
        if getattr(args, "recreate", False) and VENV_DIR.exists():
            shutil.rmtree(VENV_DIR)
        ensure_venv()
    elif args.command == "clean":
        if VENV_DIR.exists():
            shutil.rmtree(VENV_DIR)
            log("Virtualenv removed.")
        else:
            log("No virtualenv to remove.")
    elif args.command == "test":
        run_tests(args.extra)
    elif args.command == "update":
        update_repo()
    elif args.command == "doctor":
        doctor()
    elif args.command == "lock":
        lock()
    elif args.command == "sync":
        sync(args.lock_file, upgrade=args.upgrade)
    elif args.command == "clean-pyc":
        clean_pyc()
    else:
        install(
            requirements=getattr(args, "requirements", None),
            dev=getattr(args, "dev", False),
            upgrade=getattr(args, "upgrade", False),
            skip_update=getattr(args, "skip_update", False),
        )
