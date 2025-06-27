#!/usr/bin/env python3
"""Command line interface for network scanning."""
import asyncio
from argparse import ArgumentParser
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils import (  # noqa: E402
    TOP_PORTS,
    async_scan_targets,
    async_scan_targets_list,
    async_filter_active_hosts,
    ports_as_range,
    parse_ports,
    parse_hosts,
)
from rich.progress import Progress  # noqa: E402


async def main() -> None:
    parser = ArgumentParser(description="Scan multiple hosts for open ports")
    parser.add_argument(
        "ports",
        help=(
            "Ports to scan. Supports service names, ranges like '20-25', lists \n"
            "like '22,80,443', stepped ranges '20-30:2' and 'topN'."
        ),
    )
    parser.add_argument(
        "hosts",
        nargs="+",
        help="Hosts to scan. Supports CIDR, ranges and '*' wildcards",
    )
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--ttl", type=float, default=60.0, help="Cache TTL in seconds")
    parser.add_argument("--timeout", type=float, default=0.5, help="Connection timeout in seconds")
    parser.add_argument(
        "--family",
        choices=["auto", "ipv4", "ipv6"],
        default="auto",
        help="Force address family",
    )
    parser.add_argument(
        "--services",
        action="store_true",
        help="Show service names for open ports",
    )
    parser.add_argument(
        "--banner",
        action="store_true",
        help="Capture a short banner from each open port",
    )
    parser.add_argument(
        "--latency",
        action="store_true",
        help="Measure connection latency for each open port",
    )
    parser.add_argument(
        "--ping",
        action="store_true",
        help="Ping hosts before scanning and skip those that don't respond",
    )
    parser.add_argument(
        "--ping-timeout",
        type=float,
        default=1.0,
        help="Timeout for ping checks in seconds",
    )
    parser.add_argument(
        "--ping-concurrency",
        type=int,
        default=100,
        help="Number of concurrent ping checks",
    )
    parser.add_argument(
        "--top",
        type=int,
        nargs="?",
        const=100,
        help="Scan the top N common ports instead of using PORTS arg",
    )
    args = parser.parse_args()

    if args.top is not None:
        port_list = TOP_PORTS[: max(1, min(args.top, len(TOP_PORTS)))]
    else:
        try:
            port_list = parse_ports(args.ports)
        except Exception as exc:
            parser.error(str(exc))

    hosts: list[str] = []
    for spec in args.hosts:
        hosts.extend(parse_hosts(spec))

    if args.ping:
        with Progress() as progress:
            task = progress.add_task("ping", total=1.0)

            def ping_update(val: float | None) -> None:
                if val is None:
                    progress.update(task, completed=1.0)
                else:
                    progress.update(task, completed=val)

            hosts = await async_filter_active_hosts(
                hosts,
                ping_update,
                concurrency=args.ping_concurrency,
                timeout=args.ping_timeout,
            )
        if not hosts:
            print("No hosts responded to ping")
            return

    with Progress() as progress:
        task = progress.add_task("scan", total=1.0)

        def update(value: float | None) -> None:
            if value is None:
                progress.update(task, completed=1.0)
            else:
                progress.update(task, completed=value)

        fam = None
        if args.family == "ipv4":
            fam = socket.AF_INET
        elif args.family == "ipv6":
            fam = socket.AF_INET6

        start_end = ports_as_range(port_list)
        if start_end:
            start, end = start_end
            results = await async_scan_targets(
                hosts,
                start,
                end,
                concurrency=args.concurrency,
                cache_ttl=args.ttl,
                timeout=args.timeout,
                progress=update,
                family=fam,
                with_services=args.services,
                with_banner=args.banner,
                with_latency=args.latency,
            )
        else:
            results = await async_scan_targets_list(
                hosts,
                port_list,
                concurrency=args.concurrency,
                cache_ttl=args.ttl,
                timeout=args.timeout,
                progress=update,
                family=fam,
                with_services=args.services,
                with_banner=args.banner,
                with_latency=args.latency,
            )
    for host, ports in results.items():
        if not ports:
            print(f"{host}: none")
            continue
        if args.banner and isinstance(ports, dict):
            details = ", ".join(
                f"{p}({info.service}:{info.banner or ''})" for p, info in ports.items()
            )
            print(f"{host}: {details}")
        elif args.services and isinstance(ports, dict):
            details = ", ".join(f"{p}({svc})" for p, svc in ports.items())
            print(f"{host}: {details}")
        elif args.latency and isinstance(ports, dict):
            details = ", ".join(
                f"{p}({info.latency*1000:.1f}ms)" if info.latency is not None else str(p)
                for p, info in ports.items()
            )
            print(f"{host}: {details}")
        else:
            print(f"{host}: {', '.join(str(p) for p in ports)}")


if __name__ == "__main__":
    asyncio.run(main())
