"""Argument parsing and CLI orchestration for the setup command."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Sequence

from ._commands import (
    check_outdated,
    clean_pyc,
    collect_problems,
    doctor,
    install,
    lock,
    run_tests,
    self_update,
    show_info,
    sync,
    update_repo,
)
from ._logging import log
from ._state import get_venv_dir, offline_auto_detected, set_offline
from ._summary import SUMMARY, send_telemetry
from ._venv import ensure_venv

__all__ = ["main"]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="coolbox-setup",
        description="Install and inspect CoolBox deps.",
    )
    parser.add_argument("--offline", action="store_true", help="Force offline mode (skip network calls)")
    sub = parser.add_subparsers(dest="command", required=False)

    p_install = sub.add_parser("install", help="Install requirements and dev extras")
    p_install.add_argument("--requirements", type=Path, default=None)
    p_install.add_argument("--dev", action="store_true")
    p_install.add_argument("--upgrade", action="store_true")
    p_install.add_argument("--skip-update", action="store_true")
    p_install.add_argument("--no-anim", action="store_true", help="Disable animations for this run")
    p_install.add_argument("--border", action="store_true", help="Enable neon border UI")
    p_install.add_argument("--alt-screen", action="store_true", help="Use alternate screen buffer")

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

    p_prob = sub.add_parser("problems", help="Scan project for problem markers")
    p_prob.add_argument("--output", type=Path, default=None)
    p_prob.add_argument("--markers", type=str, default=None)

    p_test = sub.add_parser("test", help="Run pytest")
    p_test.add_argument("extra", nargs="*", default=[])

    sub.add_parser("update", help="git fetch/pull if repo")
    sub.add_parser("self-update", help="Update the CoolBox setup script")

    parser.set_defaults(command="install")
    _load_plugins(sub)
    return parser.parse_args(argv)


def _load_plugins(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    try:
        from importlib.metadata import entry_points
    except Exception:
        return
    try:
        for entry_point in entry_points().select(group="coolbox.plugins"):
            try:
                entry_point.load()(sub)
            except Exception as exc:  # pragma: no cover - plugin failure is non-fatal
                SUMMARY.add_warning(f"Plugin {entry_point.name} failed: {exc}")
    except Exception:
        pass


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv or sys.argv[1:])
    if getattr(args, "offline", False):
        set_offline(True)
    from ._state import is_offline  # local import to avoid cycles during module init

    is_offline()
    if offline_auto_detected():
        log("Offline mode detected (network unreachable).")
    command = args.command

    exit_code = 0
    try:
        if command == "install":
            install(
                requirements=getattr(args, "requirements", None),
                dev=getattr(args, "dev", False),
                upgrade=getattr(args, "upgrade", False),
                skip_update=getattr(args, "skip_update", False),
                no_anim=getattr(args, "no_anim", False),
                border=getattr(args, "border", None),
                alt_screen=getattr(args, "alt_screen", None),
            )
        elif command == "check":
            check_outdated(requirements=args.requirements)
        elif command == "upgrade":
            check_outdated(requirements=None, upgrade=True)
        elif command == "info":
            show_info()
        elif command == "venv":
            if getattr(args, "recreate", False):
                vdir = get_venv_dir()
                if vdir.exists():
                    shutil.rmtree(vdir, ignore_errors=True)
                    log("Virtualenv removed.")
            ensure_venv()
            log("Virtualenv ready.")
        elif command == "clean-pyc":
            clean_pyc()
        elif command == "problems":
            markers = getattr(args, "markers", None)
            collect_problems(
                output=getattr(args, "output", None),
                markers=[m.strip() for m in markers.split(",")] if markers else None,
            )
        elif command == "test":
            run_tests(args.extra)
        elif command == "update":
            update_repo()
        elif command == "doctor":
            doctor()
        elif command == "lock":
            lock()
        elif command == "sync":
            sync(args.lock_file, upgrade=args.upgrade)
        elif command == "self-update":
            self_update()
        else:
            install()
    except KeyboardInterrupt:
        SUMMARY.add_warning("Interrupted by user.")
        exit_code = 130
    except BaseException as exc:
        SUMMARY.add_error(f"Fatal: {exc.__class__.__name__}: {exc}")
        exit_code = 1
        raise
    finally:
        if command != "problems":
            try:
                collect_problems()
            except Exception as exc:
                SUMMARY.add_error(f"Problem scan failed: {exc}")
        SUMMARY.render()
        send_telemetry(SUMMARY)
        if exit_code == 0 and SUMMARY.errors:
            exit_code = 1
        sys.exit(exit_code)
