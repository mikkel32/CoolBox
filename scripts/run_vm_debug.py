#!/usr/bin/env python3
"""Launch CoolBox in a VM or container for debugging."""
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Callable
from importlib.util import module_from_spec, spec_from_file_location
import socket

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def available_backends() -> list[str]:
    """Return installed VM backends without importing the package."""
    vm_path = ROOT / "src" / "utils" / "vm.py"
    spec = spec_from_file_location("_coolbox_vm", vm_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load {vm_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return getattr(module, "available_backends")()


def _load_launch() -> 'Callable[[str | None, bool, int, bool, str | None, bool, bool, bool], bool]':
    """Load :func:`launch_vm_debug` without importing heavy deps."""
    vm_path = ROOT / "src" / "utils" / "vm.py"
    spec = spec_from_file_location("_coolbox_vm", vm_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load {vm_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return getattr(module, "launch_vm_debug")


def pick_port(start: int = 5678, count: int = 10) -> int:
    """Return a free TCP port starting at *start* within *count* attempts."""

    for port in range(start, start + count + 1):
        with socket.socket() as s:
            try:
                s.bind(("", port))
            except OSError:
                continue
            return port
    return start


def parse_args(argv: list[str] | None = None) -> Namespace:
    """Return parsed command-line arguments."""
    parser = ArgumentParser(description="Launch CoolBox for debugging")
    parser.add_argument(
        "--prefer",
        choices=["docker", "vagrant", "auto"],
        default="auto",
        help="Preferred backend (docker or vagrant)",
    )
    parser.add_argument(
        "--code",
        action="store_true",
        help="Open VS Code once the environment starts",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5678,
        help="Debug port to use when launching the environment",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available VM backends and exit",
    )
    parser.add_argument(
        "--skip-deps",
        action="store_true",
        help="Skip installing Python dependencies in the VM",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress status messages",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait for debugger to attach",
    )
    parser.add_argument(
        "--detach",
        action="store_true",
        help="Launch VM in the background and return immediately",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.list:
        print("Available backends:", " ".join(available_backends()) or "none")
        return

    launch = _load_launch()
    if not args.quiet:
        print(
            "Starting debug environment using",
            args.prefer if args.prefer != "auto" else "auto-detected backend",
        )
    port = pick_port(args.port)
    if port != args.port and not args.quiet:
        print(f"Debug port {args.port} in use; using {port}")
    success = launch(
        prefer=args.prefer if args.prefer != "auto" else None,
        open_code=args.code,
        port=port,
        skip_deps=args.skip_deps,
        print_output=not args.quiet,
        nowait=args.no_wait,
        detach=args.detach,
    )
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
