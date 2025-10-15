#!/usr/bin/env python3
"""Launch CoolBox in a VM or container for debugging."""
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Protocol
from importlib.util import module_from_spec, spec_from_file_location

import sys


class _LaunchVMDebug(Protocol):
    def __call__(
        self,
        *,
        prefer: str | None = ...,  # noqa: D401 - keyword-only mirror of API
        open_code: bool = ...,  # noqa: D401 - keyword-only mirror of API
        port: int = ...,  # noqa: D401 - keyword-only mirror of API
        skip_deps: bool = ...,  # noqa: D401 - keyword-only mirror of API
    ) -> None:
        """Protocol describing the :func:`launch_vm_debug` callable."""

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


def _load_launch() -> _LaunchVMDebug:
    """Load :func:`launch_vm_debug` without importing heavy deps."""
    vm_path = ROOT / "src" / "utils" / "vm.py"
    spec = spec_from_file_location("_coolbox_vm", vm_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load {vm_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return getattr(module, "launch_vm_debug")


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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.list:
        print("Available backends:", " ".join(available_backends()) or "none")
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
        skip_deps=args.skip_deps,
    )


if __name__ == "__main__":
    main()
