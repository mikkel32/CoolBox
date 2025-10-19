from __future__ import annotations

import argparse
import os
import time
from queue import Queue
from typing import TYPE_CHECKING

from rich.console import Console, Group  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.live import Live  # noqa: E402

if TYPE_CHECKING:
    from coolbox.utils.processes.monitor import ProcessEntry, ProcessWatcher
else:  # pragma: no cover - dynamic re-export
    from coolbox.utils.process_monitor import ProcessEntry, ProcessWatcher


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Console process monitor")
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("FORCE_QUIT_INTERVAL", "2.0")),
        help="Refresh interval in seconds",
    )
    parser.add_argument(
        "--auto-interval",
        action="store_true",
        default=os.getenv("FORCE_QUIT_AUTO_INTERVAL", "true").lower() in {"1", "true", "yes"},
        help="Enable adaptive interval tuning",
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=float(os.getenv("FORCE_QUIT_MIN_INTERVAL", "0.5")),
        help="Minimum refresh interval",
    )
    parser.add_argument(
        "--max-interval",
        type=float,
        default=float(os.getenv("FORCE_QUIT_MAX_INTERVAL", "10.0")),
        help="Maximum refresh interval",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("FORCE_QUIT_BATCH_SIZE", "100")),
        help="Number of processes to scan per cycle",
    )
    parser.add_argument(
        "--auto-batch",
        action="store_true",
        default=os.getenv("FORCE_QUIT_AUTO_BATCH", "true").lower() in {"1", "true", "yes"},
        help="Enable adaptive batch sizing",
    )
    parser.add_argument(
        "--min-batch",
        type=int,
        default=int(os.getenv("FORCE_QUIT_MIN_BATCH", "25")),
        help="Minimum batch size",
    )
    parser.add_argument(
        "--max-batch",
        type=int,
        default=int(os.getenv("FORCE_QUIT_MAX_BATCH", "1000")),
        help="Maximum batch size",
    )
    parser.add_argument(
        "--min-workers",
        type=int,
        default=int(os.getenv("FORCE_QUIT_MIN_WORKERS", "2")),
        help="Minimum worker threads",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=int(os.getenv("FORCE_QUIT_MAX_WORKERS", "16")),
        help="Maximum worker threads",
    )
    parser.add_argument(
        "--ignore-names",
        type=str,
        default=os.getenv("FORCE_QUIT_IGNORE_NAMES", ""),
        help="Comma-separated process names to ignore",
    )
    parser.add_argument(
        "--show-stats",
        action="store_true",
        default=True,
        help="Display watcher statistics",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("FORCE_QUIT_MAX", "20")),
        help="Maximum number of processes to display",
    )
    return parser.parse_args(argv)


def make_table(snapshot: dict[int, ProcessEntry], limit: int) -> Table:
    table = Table(title="Process Monitor", expand=True)
    table.add_column("PID", justify="right")
    table.add_column("Name")
    table.add_column("CPU%", justify="right")
    table.add_column("Mem MB", justify="right")
    for entry in sorted(snapshot.values(), key=lambda e: e.cpu, reverse=True)[:limit]:
        table.add_row(
            str(entry.pid),
            entry.name,
            f"{entry.cpu:.1f}",
            f"{entry.mem:.1f}",
        )
    return table


def run_cli(args: argparse.Namespace) -> None:
    q: Queue = Queue()
    watcher = ProcessWatcher(
        q,
        interval=args.interval,
        batch_size=args.batch_size,
        auto_batch=args.auto_batch,
        min_batch_size=args.min_batch,
        max_batch_size=args.max_batch,
        adaptive=args.auto_interval,
        min_interval=args.min_interval,
        max_interval=args.max_interval,
        min_workers=args.min_workers,
        max_worker_limit=args.max_workers,
        limit=args.limit,
        ignore_names={n.strip().lower() for n in args.ignore_names.split(',') if n.strip()},
    )
    watcher.start()
    console = Console()
    snapshot: dict[int, ProcessEntry] = {}

    def display() -> Group:
        group = [make_table(snapshot, args.limit)]
        if args.show_stats:
            stats = (
                f"Trend {watcher.recent_trend_ratio * 100:.0f}% | "
                f"Changed {watcher.recent_change_ratio * 100:.0f}% | "
                f"Batch {watcher.batch_size} (avg {watcher.average_batch_size:.0f}) | "
                f"Cycle {watcher.average_cycle_time:.2f}s | Int {watcher.average_interval:.2f}s | "
                f"Thr {watcher.average_throughput:.0f}/s | Workers {watcher.worker_count}"
            )
            stats_table = Table.grid()
            stats_table.add_column()
            stats_table.add_row(stats)
            group.append(stats_table)
        return Group(*group)

    with Live(console=console, refresh_per_second=4) as live:
        try:
            while True:
                while not q.empty():
                    updates, removed = q.get_nowait()
                    snapshot.update(updates)
                    for pid in removed:
                        snapshot.pop(pid, None)
                live.update(display())
                time.sleep(watcher.interval)
        except KeyboardInterrupt:
            pass
        finally:
            watcher.stop()


if __name__ == "__main__":
    run_cli(parse_args())
