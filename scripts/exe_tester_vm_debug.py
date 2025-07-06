#!/usr/bin/env python3
"""Launch the executable tester inside a VM debug environment."""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils import launch_vm_debug
import socket



def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run exe tester in VM debug mode")
    parser.add_argument("exe", help="Target executable path")
    parser.add_argument("tester_args", nargs=argparse.REMAINDER, help="Additional arguments for exe_tester.py")
    parser.add_argument("--prefer", choices=["docker", "vagrant", "auto"], default="auto", help="Preferred backend")
    parser.add_argument("--code", action="store_true", help="Open VS Code once the VM starts")
    parser.add_argument(
        "--port",
        type=int,
        default=5678,
        help="Debug port to use when launching the environment",
    )
    parser.add_argument("--skip-deps", action="store_true", help="Skip installing dependencies in the VM")
    parser.add_argument("--quiet", action="store_true", help="Suppress status messages")
    parser.add_argument("--no-wait", action="store_true", help="Do not wait for debugger attach")
    parser.add_argument(
        "--detach",
        action="store_true",
        help="Launch VM in the background and return immediately",
    )
    return parser.parse_args(argv)


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


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    tester = Path(__file__).with_name("exe_tester.py")
    target = shlex.quote(str(tester)) + " " + " ".join(shlex.quote(a) for a in [args.exe] + args.tester_args)
    port = pick_port(args.port)
    if port != args.port:
        print(f"Debug port {args.port} in use; using {port}")
    ok = launch_vm_debug(
        prefer=None if args.prefer == "auto" else args.prefer,
        open_code=args.code,
        port=port,
        skip_deps=args.skip_deps,
        target=target,
        print_output=not args.quiet,
        nowait=args.no_wait,
        detach=args.detach,
    )
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
