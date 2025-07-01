#!/usr/bin/env python3
"""
CoolBox - A Modern Desktop Application
Main entry point for the application
"""
import os
import sys
from pathlib import Path
from argparse import ArgumentParser
import hashlib
import importlib.util

from src.utils import launch_vm_debug

# Ensure package imports work when running as a script before other imports.
sys.path.insert(0, str(Path(__file__).parent))

from src import CoolBoxApp  # noqa: E402


def _compute_setup_state(root: Path) -> str:
    """Return a digest representing the current setup inputs."""
    h = hashlib.sha256()
    for name in ("requirements.txt", "setup.py"):
        fp = root / name
        if fp.is_file():
            h.update(fp.read_bytes())
    pyver = f"{sys.executable}:{sys.version_info.major}.{sys.version_info.minor}"
    h.update(pyver.encode())
    return h.hexdigest()


def _requirements_satisfied(req_path: Path) -> bool:
    """Return ``True`` if all packages from ``req_path`` are installed."""
    try:
        import pkg_resources
    except Exception:
        return False

    reqs: list[str] = []
    for line in req_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        reqs.append(line)

    if not reqs:
        return True

    try:
        pkg_resources.require(reqs)
        return True
    except Exception:
        return False


def _run_setup_if_needed(root: Path | None = None) -> None:
    """Run ``setup.py`` when requirements changed or packages missing."""
    if os.environ.get("SKIP_SETUP") == "1":
        return

    root = root or Path(__file__).resolve().parent
    sentinel = root / ".setup_done"
    current = _compute_setup_state(root)
    requirements = root / "requirements.txt"

    if sentinel.is_file() and requirements.is_file():
        try:
            recorded = sentinel.read_text().strip()
            if recorded == current and _requirements_satisfied(requirements):
                return
        except Exception:
            pass

    setup_script = root / "setup.py"
    if not setup_script.is_file():
        return

    try:
        spec = importlib.util.spec_from_file_location("coolbox_setup", setup_script)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.show_setup_banner()
            module.check_python_version()
            module.install(skip_update=True)
        if requirements.is_file():
            sentinel.write_text(current)
    except Exception as exc:  # pragma: no cover - best effort setup
        print(f"warning: failed to run setup: {exc}")


def main() -> None:
    """Initialize and run the application."""
    parser = ArgumentParser(description="CoolBox application")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run under debugpy and wait for debugger to attach",
    )
    parser.add_argument(
        "--debug-port",
        type=int,
        default=5678,
        help="Port for debugpy or --vm-debug listener (default: 5678)",
    )
    parser.add_argument(
        "--vm-debug",
        action="store_true",
        help="Launch inside a VM or container and wait for debugger",
    )
    parser.add_argument(
        "--vm-prefer",
        choices=["docker", "vagrant", "podman", "auto"],
        default="auto",
        help="Preferred VM backend for --vm-debug",
    )
    parser.add_argument(
        "--open-code",
        action="store_true",
        help="Open VS Code when launching --vm-debug",
    )
    args = parser.parse_args()

    if args.vm_debug:
        launch_vm_debug(
            prefer=None if args.vm_prefer == "auto" else args.vm_prefer,
            open_code=args.open_code,
            port=args.debug_port,
        )
        return

    if args.debug:
        try:
            import debugpy  # type: ignore

            debugpy.listen(args.debug_port)
            print(f"Waiting for debugger on port {args.debug_port}...")
            debugpy.wait_for_client()
        except Exception as exc:  # pragma: no cover - debug only
            print(f"Failed to start debugpy: {exc}")

    _run_setup_if_needed()

    app = CoolBoxApp()
    app.run()


if __name__ == "__main__":
    main()
