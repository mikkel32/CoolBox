#!/usr/bin/env python3
"""Command line interface for network scanning."""
import asyncio
from argparse import ArgumentParser
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils import async_scan_targets  # noqa: E402


async def main() -> None:
    parser = ArgumentParser(description="Scan multiple hosts for open ports")
    parser.add_argument("ports", help="Port or range like 22 or 20-25")
    parser.add_argument("hosts", nargs="+", help="Hosts to scan")
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--ttl", type=float, default=60.0, help="Cache TTL in seconds")
    args = parser.parse_args()

    if "-" in args.ports:
        start, end = [int(p) for p in args.ports.split("-", 1)]
    else:
        start = end = int(args.ports)

    results = await async_scan_targets(
        args.hosts,
        start,
        end,
        concurrency=args.concurrency,
        cache_ttl=args.ttl,
    )
    for host, ports in results.items():
        if ports:
            print(f"{host}: {', '.join(str(p) for p in ports)}")
        else:
            print(f"{host}: none")


if __name__ == "__main__":
    asyncio.run(main())
