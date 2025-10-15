#!/usr/bin/env python3
"""Command line interface for network scanning."""
import asyncio
from argparse import ArgumentParser
from pathlib import Path
import socket
import sys
from typing import TypeGuard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.utils.network as network  # noqa: E402

from src.utils import (  # noqa: E402
    TOP_PORTS,
    AutoScanInfo,
    async_scan_hosts_detailed,
    async_detect_local_hosts,
    clear_scan_cache,
    clear_host_cache,
    clear_dns_cache,
    clear_local_host_cache,
    clear_http_cache,
    clear_ping_cache,
    ports_as_range,
    parse_ports,
    parse_hosts,
)
from rich.progress import Progress  # noqa: E402


def _is_port_info_map(value: object) -> TypeGuard[dict[int, network.PortInfo]]:
    return isinstance(value, dict) and all(
        isinstance(info, network.PortInfo) for info in value.values()
    )


def _is_service_map(value: object) -> TypeGuard[dict[int, str]]:
    return isinstance(value, dict) and all(isinstance(info, str) for info in value.values())


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
        nargs="*",
        help="Hosts to scan. Supports CIDR, ranges and '*' wildcards",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Automatically detect active local hosts",
    )
    parser.add_argument(
        "--max-hosts",
        type=int,
        default=256,
        help="Limit the number of hosts per local network when auto-detecting",
    )
    parser.add_argument(
        "--no-host-cache",
        action="store_true",
        help="Disable caching of detected local hosts",
    )
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--ttl", type=float, default=60.0, help="Cache TTL in seconds")
    parser.add_argument(
        "--timeout", type=float, default=0.5, help="Connection timeout in seconds"
    )
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
        "--ping-latency",
        action="store_true",
        help="Measure latency when pinging hosts",
    )
    parser.add_argument(
        "--ping-ttl",
        action="store_true",
        help="Record TTL from ping replies",
    )
    parser.add_argument(
        "--os",
        action="store_true",
        help="Guess operating system from ping TTL",
    )
    parser.add_argument(
        "--hostname",
        action="store_true",
        help="Show hostnames in results",
    )
    parser.add_argument(
        "--mac",
        action="store_true",
        help="Show MAC addresses for hosts",
    )
    parser.add_argument(
        "--vendor",
        action="store_true",
        help="Show MAC vendor names",
    )
    parser.add_argument(
        "--connections",
        action="store_true",
        help="Show active connection counts (local hosts only)",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Collect basic HTTP info for web ports",
    )
    parser.add_argument(
        "--http-concurrency",
        type=int,
        default=network._DEFAULT_HTTP_CONCURRENCY,
        help="Number of concurrent HTTP requests",
    )
    parser.add_argument(
        "--host-concurrency",
        type=int,
        default=network._DEFAULT_HOST_CONCURRENCY,
        help="Number of hosts scanned concurrently",
    )
    parser.add_argument(
        "--device",
        action="store_true",
        dest="device_type",
        help="Guess device type for each host",
    )
    parser.add_argument(
        "--risk",
        action="store_true",
        help="Show risk score per host",
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
        default=network._DEFAULT_PING_CONCURRENCY,
        help="Number of concurrent ping checks",
    )
    parser.add_argument(
        "--top",
        type=int,
        nargs="?",
        const=100,
        help="Scan the top N common ports instead of using PORTS arg",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear cached results before scanning",
    )
    parser.add_argument(
        "--json",
        nargs="?",
        const="-",
        metavar="FILE",
        help="Write results as JSON to FILE or stdout",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream JSON results as they are found",
    )
    args = parser.parse_args()

    if args.clear_cache:
        clear_scan_cache()
        clear_host_cache()
        clear_dns_cache()
        clear_local_host_cache()
        clear_http_cache()
        clear_ping_cache()

    if args.top is not None:
        port_list = TOP_PORTS[: max(1, min(args.top, len(TOP_PORTS)))]
    else:
        try:
            port_list = parse_ports(args.ports)
        except Exception as exc:
            parser.error(str(exc))

    manual_hosts: list[str] = []
    for spec in args.hosts:
        manual_hosts.extend(parse_hosts(spec))

    if args.auto:
        with Progress(disable=bool(args.json)) as progress:
            task = progress.add_task("detect", total=1.0)

            def det_update(val: float | None) -> None:
                if val is None:
                    progress.update(task, completed=1.0)
                else:
                    progress.update(task, completed=val)

            res = await async_detect_local_hosts(
                progress=det_update,
                concurrency=args.ping_concurrency,
                timeout=args.ping_timeout,
                max_hosts_per_network=args.max_hosts,
                use_cache=not args.no_host_cache,
            )
        if not res:
            print("No hosts detected")
            return
        hosts = list(dict.fromkeys(list(res) + manual_hosts))
    else:
        hosts = list(dict.fromkeys(manual_hosts))

    if not hosts:
        parser.error("No hosts specified")

    with Progress(disable=bool(args.json)) as progress:
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
            ports_param = None
        else:
            start, end = port_list[0], port_list[-1]
            ports_param = port_list

        if args.stream and args.json is not None:
            from src.utils import (
                auto_scan_info_to_dict,
                async_auto_scan_iter,
                async_scan_hosts_iter,
            )
            import json

            scan_iter = (
                async_auto_scan_iter(
                    start,
                    end,
                    update,
                    concurrency=args.concurrency,
                    ports=ports_param,
                    cache_ttl=args.ttl,
                    family=fam,
                    timeout=args.timeout,
                    ping_concurrency=args.ping_concurrency,
                    ping_timeout=args.ping_timeout,
                    with_services=args.services,
                    with_banner=args.banner,
                    with_latency=args.latency,
                    with_hostname=args.hostname,
                    with_mac=args.mac,
                    with_connections=args.connections,
                    with_vendor=args.vendor,
                    with_http_info=args.http,
                    host_concurrency=args.host_concurrency,
                    http_concurrency=args.http_concurrency,
                    with_device_type=args.device_type,
                    with_risk_score=args.risk,
                    with_os=args.os,
                    with_ttl=args.ping_ttl,
                    with_ping_latency=args.ping_latency,
                )
                if args.auto
                else async_scan_hosts_iter(
                    hosts,
                    start,
                    end,
                    update,
                    concurrency=args.concurrency,
                    ports=ports_param,
                    cache_ttl=args.ttl,
                    family=fam,
                    timeout=args.timeout,
                    ping=args.ping,
                    ping_concurrency=args.ping_concurrency,
                    ping_timeout=args.ping_timeout,
                    with_services=args.services,
                    with_banner=args.banner,
                    with_latency=args.latency,
                    with_hostname=args.hostname,
                    with_mac=args.mac,
                    with_connections=args.connections,
                    with_vendor=args.vendor,
                    with_http_info=args.http,
                    host_concurrency=args.host_concurrency,
                    http_concurrency=args.http_concurrency,
                    with_device_type=args.device_type,
                    with_risk_score=args.risk,
                    with_os=args.os,
                    with_ttl=args.ping_ttl,
                    with_ping_latency=args.ping_latency,
                )
            )

            async for host, info in scan_iter:
                data = {host: auto_scan_info_to_dict(info) if isinstance(info, AutoScanInfo) else info}
                if args.json == "-":
                    print(json.dumps(data))
                else:
                    with open(args.json, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(data) + "\n")
            return
        else:
            results = await async_scan_hosts_detailed(
                hosts,
                start,
                end,
                update,
                concurrency=args.concurrency,
                ports=ports_param,
                cache_ttl=args.ttl,
                family=fam,
                timeout=args.timeout,
                ping=args.ping,
                ping_concurrency=args.ping_concurrency,
                ping_timeout=args.ping_timeout,
                with_services=args.services,
                with_banner=args.banner,
                with_latency=args.latency,
                with_hostname=args.hostname,
                with_mac=args.mac,
                with_connections=args.connections,
                with_vendor=args.vendor,
                with_http_info=args.http,
                host_concurrency=args.host_concurrency,
                http_concurrency=args.http_concurrency,
                with_device_type=args.device_type,
                with_risk_score=args.risk,
                with_os=args.os,
                with_ttl=args.ping_ttl,
                with_ping_latency=args.ping_latency,
            )

    if args.json is not None:
        from src.utils import auto_scan_results_to_dict
        data = auto_scan_results_to_dict(results)
        if args.json == "-":
            import json

            json.dump(data, sys.stdout, indent=2)
            print()
        else:
            import json

            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        return

    for host, info in results.items():
        ports = info.ports
        if not ports:
            print(f"{host}: none")
            continue

        prefix = host
        if args.hostname and info.hostname:
            prefix += f" ({info.hostname})"
        if args.mac and info.mac:
            prefix += f" [{info.mac}]"
        if args.vendor and info.vendor:
            prefix += f" <{info.vendor}>"
        if args.os and info.os_guess:
            prefix += f" {{{info.os_guess}}}"
        if args.ping_ttl and info.ttl is not None:
            prefix += f" <TTL:{info.ttl}>"
        if args.ping_latency and info.ping_latency is not None:
            prefix += f" [{info.ping_latency * 1000:.1f}ms]"
        if args.device_type and info.device_type:
            prefix += f" [{info.device_type}]"
        if args.risk and info.risk_score is not None:
            prefix += f" <Risk:{info.risk_score}>"

        if args.banner and _is_port_info_map(ports):
            details = ", ".join(
                f"{port}({port_info.service}:{port_info.banner or ''})"
                for port, port_info in ports.items()
            )
            print(f"{prefix}: {details}")
        elif args.services and _is_service_map(ports):
            details = ", ".join(f"{port}({service})" for port, service in ports.items())
            print(f"{prefix}: {details}")
        elif args.latency and _is_port_info_map(ports):
            details = ", ".join(
                (
                    f"{port}({port_info.latency * 1000:.1f}ms)"
                    if port_info.latency is not None
                    else str(port)
                )
                for port, port_info in ports.items()
            )
            print(f"{prefix}: {details}")
        elif args.http and info.http_info and isinstance(ports, (list, dict)):
            details = []
            port_iter = ports.keys() if isinstance(ports, dict) else ports
            for p in port_iter:
                base = str(p)
                meta = info.http_info.get(p) if info.http_info else None
                if meta:
                    if meta.server:
                        base += f"<{meta.server}>"
                    elif meta.title:
                        base += f"<{meta.title}>"
                details.append(base)
            print(f"{prefix}: {', '.join(details)}")
        else:
            port_list = ports.keys() if isinstance(ports, dict) else ports
            items = []
            for p in port_list:
                item = str(p)
                if args.connections and info.connections is not None:
                    cnt = info.connections.get(p, 0)
                    if cnt:
                        item += f"[{cnt}]"
                items.append(item)
            print(f"{prefix}: {', '.join(items)}")


if __name__ == "__main__":
    asyncio.run(main())
