#!/usr/bin/env python3
"""Launch CoolBox in a VM or container for debugging."""
from argparse import ArgumentParser
from pathlib import Path
from typing import Callable
from importlib.util import module_from_spec, spec_from_file_location
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_launch() -> 'Callable[[str | None, bool, int], None]':
    """Load :func:`launch_vm_debug` without importing heavy deps."""
    vm_path = ROOT / "src" / "utils" / "vm.py"
    spec = spec_from_file_location("_coolbox_vm", vm_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load {vm_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return getattr(module, "launch_vm_debug")


def _available_backends() -> list[str]:
    """Return a list of available VM backends."""
    backends = []
    for name in ("docker", "podman", "vagrant"):
        if shutil.which(name):
            backends.append(name)
    return backends


def main() -> None:
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
    args = parser.parse_args()

    if args.list:
        print("Available backends:", " ".join(_available_backends()) or "none")
        return

    launch = _load_launch()
    print(
        "Starting debug environment using",
        args.prefer if args.prefer != "auto" else "auto-detected backend",
    )
    launch(
        prefer=args.prefer if args.prefer != "auto" else None,
        open_code=args.code,
        port=args.port,
    )


if __name__ == "__main__":
    main()
