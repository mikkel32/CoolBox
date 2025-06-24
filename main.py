#!/usr/bin/env python3
"""
CoolBox - A Modern Desktop Application
Main entry point for the application
"""
import sys
from pathlib import Path
from argparse import ArgumentParser

from src.utils import launch_vm_debug

# Ensure package imports work when running as a script before other imports.
sys.path.insert(0, str(Path(__file__).parent))

from src import CoolBoxApp  # noqa: E402


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
        help="Port for debugpy to listen on (default: 5678)",
    )
    parser.add_argument(
        "--vm-debug",
        action="store_true",
        help="Launch inside a VM or container and wait for debugger",
    )
    args = parser.parse_args()

    if args.vm_debug:
        launch_vm_debug()
        return

    if args.debug:
        try:
            import debugpy  # type: ignore

            debugpy.listen(args.debug_port)
            print(f"Waiting for debugger on port {args.debug_port}...")
            debugpy.wait_for_client()
        except Exception as exc:  # pragma: no cover - debug only
            print(f"Failed to start debugpy: {exc}")

    app = CoolBoxApp()
    app.run()


if __name__ == "__main__":
    main()
