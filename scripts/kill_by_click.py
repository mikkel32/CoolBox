#!/usr/bin/env python3
"""Select a window by clicking it and print the PID and title."""

import argparse
import sys
import tkinter as tk
from typing import Protocol, runtime_checkable, cast

from src.views.click_overlay import ClickOverlay, KILL_BY_CLICK_INTERVAL


@runtime_checkable
class _OverlayChooser(Protocol):
    """Simple protocol implemented by overlay backends that can select a window."""

    def choose(self) -> tuple[int | None, str | None]:
        ...


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
        default=KILL_BY_CLICK_INTERVAL,
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
        "--calibrate",
        action="store_true",
        help="Re-run interval calibration and exit",
    )
    args = parser.parse_args(argv)

    for name in ["interval", "min_interval", "max_interval", "delay_scale"]:
        value = getattr(args, name)
        if value is not None and value <= 0:
            parser.error(f"{name.replace('_', '-')} must be positive")
    if args.min_interval is not None and args.max_interval is not None:
        if args.min_interval > args.max_interval:
            parser.error("min-interval cannot exceed max-interval")
    if args.min_interval is not None and args.interval < args.min_interval:
        parser.error("interval must be at least min-interval")
    if args.max_interval is not None and args.interval > args.max_interval:
        parser.error("interval must be at most max-interval")

    if args.calibrate:
        interval, min_i, max_i = ClickOverlay.auto_tune_interval()
        print(f"Calibrated: interval={interval:.4f} min={min_i:.4f} max={max_i:.4f}")
        return

    try:
        root = tk.Tk()
    except tk.TclError:
        print("No display available")
        sys.exit(1)
    root.withdraw()
    kwargs = {"skip_confirm": args.skip_confirm, "interval": args.interval}
    if args.min_interval is not None:
        kwargs["min_interval"] = args.min_interval
    if args.max_interval is not None:
        kwargs["max_interval"] = args.max_interval
    if args.delay_scale is not None:
        kwargs["delay_scale"] = args.delay_scale
    try:
        overlay = ClickOverlay(root, **kwargs)
        chooser = cast(_OverlayChooser, overlay)
        pid, title = chooser.choose()
        if pid is None:
            print("No window selected")
        else:
            print(f"{pid} {title or ''}")
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
