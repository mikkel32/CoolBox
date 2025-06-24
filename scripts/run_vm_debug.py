#!/usr/bin/env python3
"""Launch CoolBox in a VM or container for debugging."""
from argparse import ArgumentParser
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils import launch_vm_debug  # noqa: E402


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
    args = parser.parse_args()

    launch_vm_debug(prefer=args.prefer if args.prefer != "auto" else None, open_code=args.code)


if __name__ == "__main__":
    main()
