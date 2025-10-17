"""High level setup commands and actions."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from typing import Sequence

from ._config import CONFIG
from ._execution import _retry, _run
from ._helpers import ensure_numpy, get_system_info
from ._logging import log
from ._pip import (
    _build_install_plan,
    _execute_install_plan,
    _pip,
    _restore_wheel_artifacts,
    _store_wheel_artifacts,
    _write_req_stamp,
)
from ._state import BASE_ENV, ROOT_DIR, REQUIREMENTS_FILE, is_offline
from ._summary import SUMMARY
from ._ui import Panel, Table, Text, console, create_progress, rainbow_text, NeonPulseBorder, box
from ._venv import ensure_venv
from .version import __version__

__all__ = [
    "build_extensions",
    "check_outdated",
    "clean_pyc",
    "collect_problems",
    "doctor",
    "install",
    "lock",
    "run_tests",
    "self_update",
    "show_info",
    "show_setup_banner",
    "sync",
    "update_repo",
]


def show_setup_banner() -> None:
    banner = rainbow_text(f" CoolBox setup v{__version__} ")
    path = Text(str(ROOT_DIR), style="bold magenta")
    content = Text.assemble(banner, "\n", path)
    console.print(Panel(content, box=box.ROUNDED, expand=False))


def update_repo() -> None:
    if CONFIG.no_git or is_offline():
        log("Skip git update (disabled or offline).")
        return
    if not (ROOT_DIR / ".git").exists():
        log("No .git directory. Skipping update.")
        return
    log("Updating repository...")
    try:
        _retry(["git", "-C", str(ROOT_DIR), "fetch", "--all", "--tags", "--prune"], attempts=2)
        _retry(["git", "-C", str(ROOT_DIR), "pull", "--rebase", "--autostash"], attempts=2)
    except Exception as exc:
        SUMMARY.add_warning(f"git update failed: {exc}")


def build_extensions() -> None:
    dist_dir = ROOT_DIR / "dist"
    if is_offline():
        if _restore_wheel_artifacts(dist_dir):
            log("Offline mode: restored cached wheel artifacts.")
        else:
            SUMMARY.add_warning("Offline mode: no cached wheels available for reuse.")
        return
    try:
        py = ensure_venv()
        _run([py, "-m", "build", "--wheel", "--no-isolation"], cwd=ROOT_DIR)
    except Exception as exc:
        SUMMARY.add_warning(f"native build skipped: {exc}")
        if _restore_wheel_artifacts(dist_dir):
            log("Used cached wheel artifacts after build failure.")
    else:
        _store_wheel_artifacts(dist_dir)


def check_outdated(*, requirements: Path | None, upgrade: bool = False) -> None:
    py = ensure_venv()
    cmd = [py, "-m", "pip", "list", "--outdated", "--format=json"]
    try:
        output = subprocess.check_output(cmd, text=True, env=BASE_ENV)
        packages = json.loads(output)
    except Exception as exc:
        SUMMARY.add_warning(f"pip list --outdated failed: {exc}")
        packages = []
    if upgrade and packages:
        with create_progress() as progress:
            task = progress.add_task("Upgrading outdated packages", total=len(packages))

            def _worker(name: str) -> None:
                try:
                    _pip(["install", "-U", name], upgrade_pip=False, attempts=2)
                except Exception as error:
                    SUMMARY.add_error(f"Upgrade {name} failed: {error}")
                finally:
                    progress.advance(task)

            with ThreadPoolExecutor() as executor:
                for package in packages:
                    name = package.get("name")
                    if name:
                        executor.submit(_worker, name)
    else:
        table = Table(title="Outdated packages", box=box.SIMPLE_HEAVY)
        table.add_column("Name")
        table.add_column("Version")
        table.add_column("Latest")
        table.add_column("Type")
        for package in packages:
            table.add_row(
                package.get("name", ""),
                package.get("version", ""),
                package.get("latest_version", ""),
                package.get("type", ""),
            )
        console.print(table)


def show_info() -> None:
    info = get_system_info()
    if isinstance(info, dict):
        table = Table(title="CoolBox — System Info", box=box.MINIMAL_DOUBLE_HEAD)
        for key, value in info.items():
            table.add_row(key, str(value))
        console.print(table)
    else:
        console.print(info)


def run_tests(extra: Sequence[str]) -> None:
    py = ensure_venv()
    with create_progress() as progress:
        task = progress.add_task("Running tests", total=1)
        try:
            _run([py, "-m", "pytest", "-q", *extra])
        except Exception as exc:
            SUMMARY.add_error(f"pytest failed: {exc}")
        finally:
            progress.advance(task)


def doctor() -> None:
    problems: list[str] = []
    if is_offline():
        problems.append("offline mode active, downloads disabled.")
    if CONFIG.no_git:
        problems.append("NO_GIT set, repo update disabled.")
    if not REQUIREMENTS_FILE.exists():
        problems.append("requirements.txt not found.")
    console.print(
        Panel.fit("\n".join(problems) or "No obvious problems.", title="Doctor", box=box.ROUNDED)
    )


def lock() -> None:
    py = ensure_venv()
    try:
        _pip(["install", "-U", "pip-tools"], upgrade_pip=False)
        _run([py, "-m", "piptools", "compile", str(REQUIREMENTS_FILE), "--upgrade"])
    except Exception as exc:
        SUMMARY.add_error(f"Lock failed: {exc}")


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
    except Exception as exc:
        SUMMARY.add_error(f"Sync failed: {exc}")


def self_update() -> None:
    py = ensure_venv()
    try:
        _run([py, "-m", "pip", "install", "-U", "coolbox"])
    except Exception as exc:
        SUMMARY.add_error(f"Self-update failed: {exc}")


def clean_pyc() -> None:
    removed = 0
    for path in ROOT_DIR.rglob("*"):
        if path.is_dir() and path.name == "__pycache__":
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    log(f"Removed {removed} __pycache__ folders.")


def collect_problems(output: Path | None = None, markers: Sequence[str] | None = None) -> None:
    markers = [marker.strip() for marker in (markers or ["TODO", "FIXME", "BUG", "WARNING"])]
    pattern = "|".join(re.escape(marker) for marker in markers)
    problem_re = re.compile(f"({pattern})", re.IGNORECASE)
    ignore_dirs = {".git", ".venv", "venv", "__pycache__"}
    files = [
        path
        for path in ROOT_DIR.rglob("*")
        if path.is_file() and not any(part in ignore_dirs for part in path.parts)
    ]

    def _scan(file_path: Path) -> list[tuple[str, int, str]]:
        results: list[tuple[str, int, str]] = []
        try:
            with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for lineno, line in enumerate(handle, 1):
                    if problem_re.search(line):
                        rel = file_path.relative_to(ROOT_DIR)
                        results.append((str(rel), lineno, line.rstrip()))
        except Exception as exc:
            SUMMARY.add_warning(f"Could not read {file_path}: {exc}")
        return results

    matches: list[tuple[str, int, str]] = []
    with ThreadPoolExecutor() as executor:
        for result in executor.map(_scan, files):
            matches.extend(result)
    matches.sort()

    for file_path, lineno, text in matches:
        SUMMARY.warnings.append(f"{file_path}:{lineno}: {text}")

    if output:
        output.write_text("\n".join(f"{f}:{n}: {t}" for f, n, t in matches))
        log(f"Wrote {len(matches)} problem lines to {output}")
    else:
        if matches:
            table = Table(box=box.SIMPLE_HEAVY)
            table.add_column("File", overflow="fold")
            table.add_column("Line", justify="right")
            table.add_column("Text")
            for file_path, lineno, text in matches:
                table.add_row(file_path, str(lineno), text)
            console.print(Panel(table, title=f"Problems ({len(matches)})", box=box.ROUNDED))
        else:
            log("Found 0 problem lines.")


def install(
    requirements: Path | None = None,
    *,
    dev: bool = False,
    upgrade: bool = False,
    skip_update: bool = False,
    no_anim: bool | None = None,
    border: bool | None = None,
    alt_screen: bool | None = None,
) -> None:
    os.chdir(ROOT_DIR)
    if not skip_update:
        update_repo()
    ensure_numpy()
    py = ensure_venv()

    if no_anim is True:
        CONFIG.no_anim = True
    if alt_screen is True:
        CONFIG.alt_screen = True
    border_enabled = CONFIG.border_enabled_default if border is None else bool(border)
    if CONFIG.no_anim:
        border_enabled = False

    requirements_path = requirements or REQUIREMENTS_FILE
    planned = _build_install_plan(requirements_path, dev, upgrade)
    log(f"Install plan steps: {len(planned)}")

    border_ctx = (
        NeonPulseBorder(
            speed=0.04,
            style="rounded",
            theme="pride",
            thickness=2,
            use_alt_screen=CONFIG.alt_screen,
            console=console.raw,
        )
        if border_enabled
        else nullcontext()
    )

    try:
        with border_ctx:
            show_setup_banner()
            _execute_install_plan(planned)
            try:
                _retry([py, "-m", "pip", "check"], attempts=1)
            except Exception as exc:
                SUMMARY.add_warning(f"pip check reported issues: {exc}")
            build_extensions()
    finally:
        console.flush()

    if requirements_path.is_file():
        try:
            _write_req_stamp(requirements_path)
        except Exception as exc:
            SUMMARY.add_warning(f"Could not write requirement stamp: {exc}")

    log("Done.")
