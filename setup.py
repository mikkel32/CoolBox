"""Utility helpers for installing and inspecting CoolBox dependencies."""

from __future__ import annotations

__version__ = "1.3.52"

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

try:
    from rich.text import Text
    from rich.progress import (
        Progress,
        SpinnerColumn,
        BarColumn,
        TimeElapsedColumn,
    )
except ImportError:  # pragma: no cover - runtime dependency check
    from src.ensure_deps import ensure_rich

    ensure_rich()
    from rich.text import Text
    from rich.progress import (
        Progress,
        SpinnerColumn,
        BarColumn,
        TimeElapsedColumn,
    )

from src.ensure_deps import ensure_numpy

try:  # Ensure NumPy is available for optional speedups
    ensure_numpy()
except Exception:  # pragma: no cover - dependency may be skipped
    pass

os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")  # noqa: E402
from src.utils.helpers import log, get_system_info, run_with_spinner, console  # noqa: E402
from src.utils.rainbow import NeonPulseBorder  # noqa: E402


MIN_PYTHON = (3, 10)


COOLBOX_ART = r"""
  ____            _ ____
 / ___|___   ___ | | __ )  _____  __
| |   / _ \ / _ \| |  _ \ / _ \ \/ /
| |__| (_) | (_) | | |_) | (_) >  <
 \____\___/ \___/|_|____/ \___/_/\_\
"""


def _gradient_line(line: str, offset: int = 0) -> Text:
    """Return *line* styled with a moving gradient."""
    text = Text()
    n = max(len(line) - 1, 1)
    for i, ch in enumerate(line):
        pos = ((i + offset) % len(line)) / n
        color = _blend("#00eaff", "#ff00d0", pos)
        text.append(ch, style=color)
    return text


def _blend(c1: str, c2: str, t: float) -> str:
    """Return a color between ``c1`` and ``c2`` at position ``t``."""
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


def show_setup_banner() -> None:
    """Display an animated banner with a short loading bar."""
    console.clear()
    lines = COOLBOX_ART.strip("\n").splitlines()
    with NeonPulseBorder(speed=0.05):
        for step in range(30):
            console.clear()
            for line in lines:
                console.print(_gradient_line(line, step), justify="center")
            time.sleep(0.05)

    with Progress(
        SpinnerColumn(style="bold magenta"),
        BarColumn(bar_width=None),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Initializing", total=100)
        for _ in range(100):
            progress.update(task, advance=1)
            time.sleep(0.01)

    console.rule("[bold cyan]CoolBox Setup")


def check_python_version() -> None:
    """Abort if the active Python version is too old."""
    if sys.version_info < MIN_PYTHON:
        sys.exit(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer required.")


def locate_root(start: Path | None = None) -> Path:
    """Return the CoolBox project root scanning upward from *start*."""
    start = (start or Path(__file__)).resolve()
    if start.is_file():
        start = start.parent
    for path in [start, *start.parents]:
        if (path / ".git").is_dir() or (path / "requirements.txt").is_file():
            return path
    return start


def update_repo() -> None:
    """Pull the latest changes from the repository if behind the upstream."""
    os.chdir(ROOT_DIR)
    if not (ROOT_DIR / ".git").is_dir():
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
        try:
            with NeonPulseBorder():
                run_with_spinner(
                    [
                        "git",
                        "fetch",
                        remote,
                    ],
                    message="Fetching updates",
                )
        except subprocess.CalledProcessError as exc:
            log(f"Failed to fetch updates: {exc}")
            return
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
            log(f"Repository behind upstream by {behind} commit(s); pulling...")
            with NeonPulseBorder():
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
    """Return the project root directory."""
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


def get_venv_dir() -> Path:
    env = os.environ.get("COOLBOX_VENV")
    if env:
        return Path(env).expanduser().resolve()
    return ROOT_DIR / ".venv"


REQUIREMENTS_FILE = ROOT_DIR / "requirements.txt"
VENV_DIR = get_venv_dir()
DEV_PACKAGES = ["debugpy", "flake8"]


def build_extensions() -> None:
    """Attempt to build optional Cython extensions."""

    try:
        import importlib

        cython_build = importlib.import_module("Cython.Build")
        cythonize = cython_build.cythonize
        from setuptools import Extension
        import numpy
    except Exception as exc:  # pragma: no cover - build tools missing
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
    except Exception as exc:  # pragma: no cover - compile may fail
        log(f"Failed to build Cython extensions: {exc}")


def ensure_venv(venv_dir: Path = VENV_DIR, *, python: str | None = None) -> Path:
    """Ensure a virtual environment exists and return its Python executable."""
    if sys.prefix != sys.base_prefix:
        return Path(sys.executable)

    if not venv_dir.exists():
        py_exe = python or sys.executable
        log(f"Creating virtual environment at {venv_dir} using {py_exe}")
        with NeonPulseBorder():
            run_with_spinner(
                [py_exe, "-m", "venv", str(venv_dir)],
                message="Creating virtualenv",
            )

    python_path = venv_dir / "bin" / "python"
    if not python_path.exists():  # Windows fallback
        python_path = venv_dir / "Scripts" / "python.exe"
    return python_path


def _pip(
    args: Iterable[str], python: Path | None = None, *, upgrade_pip: bool = False
) -> None:
    """Run ``pip`` using *python* with *args*, logging the command."""
    py = python or ensure_venv()
    if upgrade_pip:
        with NeonPulseBorder():
            run_with_spinner(
                [str(py), "-m", "pip", "install", "--upgrade", "pip"],
                message="Upgrading pip",
            )
    cmd = [str(py), "-m", "pip", *args]
    log("Running: " + " ".join(cmd))
    with NeonPulseBorder():
        run_with_spinner(cmd, message="Installing dependencies")


def run_tests(extra: Iterable[str] | None = None) -> None:
    """Run the test suite using pytest."""
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
    """Install dependencies using ``pip`` with optional upgrades.

    Parameters
    ----------
    requirements: Path | None, optional
        Path to the requirements file containing runtime dependencies. If
        ``None``, the default ``requirements.txt`` next to this script is used.
    dev: bool, default False
        If ``True``, install additional development packages.
    skip_update: bool, default False
        Skip checking for and pulling the latest git changes.
    """
    os.chdir(ROOT_DIR)
    if not skip_update:
        update_repo()
    py = ensure_venv()
    req_path = requirements or REQUIREMENTS_FILE
    if req_path.is_file():
        log(f"Installing requirements from {req_path}")
        args = ["install", "-r", str(req_path)]
        if upgrade:
            args.append("--upgrade")
        _pip(args, python=py, upgrade_pip=upgrade)
    else:
        log(f"Requirements file {req_path} not found")

    if dev:
        log("Installing development packages")
        for pkg in DEV_PACKAGES:
            args = ["install", pkg]
            if upgrade:
                args.append("--upgrade")
            _pip(args, python=py)

    log("Dependencies installed.")
    build_extensions()


def check_outdated(requirements: Path | None = None, *, upgrade: bool = False) -> None:
    """Log and optionally upgrade packages with newer versions available."""
    os.chdir(ROOT_DIR)
    req_path = requirements or REQUIREMENTS_FILE
    if not req_path.is_file():
        log(f"Requirements file {req_path} not found")
        return
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
    """Print detailed system information for debugging."""
    print(f"Project Root: {ROOT_DIR}")
    print(f"Virtualenv: {VENV_DIR}")
    print(get_system_info())


if __name__ == "__main__":
    show_setup_banner()
    check_python_version()
    parser = argparse.ArgumentParser(
        description="Manage CoolBox dependencies and show environment info"
    )
    sub = parser.add_subparsers(dest="command")

    install_p = sub.add_parser("install", help="Install required packages")
    install_p.add_argument(
        "--requirements",
        type=Path,
        help="Path to an alternate requirements file",
    )
    install_p.add_argument(
        "--dev", action="store_true", help="Install development packages"
    )
    install_p.add_argument(
        "--upgrade", action="store_true", help="Upgrade packages to latest versions"
    )
    install_p.add_argument(
        "--skip-update",
        action="store_true",
        help="Skip pulling the latest git changes before installing",
    )

    check_p = sub.add_parser("check", help="List outdated packages")
    check_p.add_argument(
        "--requirements",
        type=Path,
        help="Path to the requirements file",
    )

    sub.add_parser("info", help="Show system information")
    venv_p = sub.add_parser("venv", help="Create or ensure the project virtualenv")
    venv_p.add_argument(
        "--recreate", action="store_true", help="Recreate the virtual environment"
    )
    sub.add_parser("clean", help="Remove the project virtualenv")
    sub.add_parser("update", help="Pull the latest changes from the repository")
    sub.add_parser("upgrade", help="Upgrade all outdated packages")
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
        if args.recreate and VENV_DIR.exists():
            import shutil

            shutil.rmtree(VENV_DIR)
        ensure_venv()
    elif args.command == "clean":
        import shutil

        if VENV_DIR.exists():
            shutil.rmtree(VENV_DIR)
            log("Virtualenv removed.")
        else:
            log("No virtualenv to remove.")
    elif args.command == "test":
        run_tests(args.extra)
    elif args.command == "update":
        update_repo()
    else:
        install(
            requirements=getattr(args, "requirements", None),
            dev=getattr(args, "dev", False),
            upgrade=getattr(args, "upgrade", False),
            skip_update=getattr(args, "skip_update", False),
        )
