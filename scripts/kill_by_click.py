#!/usr/bin/env python3
"""Select a window by clicking it and print the PID and title."""

import argparse
import os
import tkinter as tk
from src.views.click_overlay import ClickOverlay, KILL_BY_CLICK_INTERVAL


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Select a window and output its PID")
    parser.add_argument(
        "--skip-confirm",
        action="store_true",
        help="Close immediately without verifying the click position",
    )
    parser.add_argument(
        "--interval",
        type=float,
        help=(
            "Refresh rate in seconds for the overlay. Overrides "
            "KILL_BY_CLICK_INTERVAL if provided."
        ),
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        help="Smallest allowed refresh interval in seconds",
    )
    parser.add_argument(
        "--max-interval",
        type=float,
        help="Largest allowed refresh interval in seconds",
    )
    parser.add_argument(
        "--delay-scale",
        type=float,
        help="Controls how strongly pointer speed shortens the delay",
    )
    parser.add_argument(
        "--workers",
        type=int,
        help="Number of threads to use for background window detection",
    )
    parser.add_argument(
        "--cache-timeout",
        type=float,
        help="Seconds to keep cached window info valid",
    )
    immed = parser.add_mutually_exclusive_group()
    immed.add_argument(
        "--immediate",
        dest="immediate",
        action="store_true",
        help="Trigger window queries immediately on cursor move",
    )
    immed.add_argument(
        "--no-immediate",
        dest="immediate",
        action="store_false",
        help="Disable immediate queries on movement",
    )
    heat = parser.add_mutually_exclusive_group()
    heat.add_argument(
        "--heatmap",
        dest="heatmap",
        action="store_true",
        help="Enable cursor heatmap tracking",
    )
    heat.add_argument(
        "--no-heatmap",
        dest="heatmap",
        action="store_false",
        help="Disable cursor heatmap tracking",
    )
    cache = parser.add_mutually_exclusive_group()
    cache.add_argument(
        "--cache",
        dest="cache",
        action="store_true",
        help="Enable caching of window info",
    )
    cache.add_argument(
        "--no-cache",
        dest="cache",
        action="store_false",
        help="Disable cached window info",
    )
    bg = parser.add_mutually_exclusive_group()
    bg.add_argument(
        "--background",
        dest="background",
        action="store_true",
        help="Query the window on a background thread",
    )
    bg.add_argument(
        "--no-background",
        dest="background",
        action="store_false",
        help="Disable threaded window detection",
    )
    parser.set_defaults(background=None, cache=None, heatmap=None, immediate=None)
    args = parser.parse_args(argv)

    root = tk.Tk()
    root.withdraw()
    kwargs = {"skip_confirm": args.skip_confirm}
    if args.interval is not None:
        kwargs["interval"] = args.interval
    if args.min_interval is not None:
        kwargs["min_interval"] = args.min_interval
    if args.max_interval is not None:
        kwargs["max_interval"] = args.max_interval
    if args.delay_scale is not None:
        kwargs["delay_scale"] = args.delay_scale
    if args.workers is not None:
        kwargs["workers"] = args.workers
    if args.background is not None:
        kwargs["background"] = args.background
    if args.cache_timeout is not None:
        kwargs["cache_timeout"] = args.cache_timeout
    if args.cache is not None:
        kwargs["cache"] = args.cache
    if args.heatmap is not None:
        kwargs["heatmap"] = args.heatmap
    if args.immediate is not None:
        kwargs["immediate"] = args.immediate
    overlay = ClickOverlay(root, **kwargs)
    pid, title = overlay.choose()
    if pid is None:
        print("No window selected")
    else:
        print(f"{pid} {title or ''}")
    root.destroy()


if __name__ == "__main__":
    main()
