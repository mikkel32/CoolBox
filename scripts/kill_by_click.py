#!/usr/bin/env python3
"""Select a window by clicking it and print the PID and title."""

import argparse
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

    if args.calibrate:
        interval, min_i, max_i = ClickOverlay.auto_tune_interval()
        print(f"Calibrated: interval={interval:.4f} min={min_i:.4f} max={max_i:.4f}")
        return

    root = tk.Tk()
    root.withdraw()
    kwargs = {"skip_confirm": args.skip_confirm, "interval": args.interval}
    if args.min_interval is not None:
        kwargs["min_interval"] = args.min_interval
    if args.max_interval is not None:
        kwargs["max_interval"] = args.max_interval
    if args.delay_scale is not None:
        kwargs["delay_scale"] = args.delay_scale
    overlay = ClickOverlay(root, **kwargs)
    pid, title = overlay.choose()
    if pid is None:
        print("No window selected")
    else:
        print(f"{pid} {title or ''}")
    root.destroy()


if __name__ == "__main__":
    main()
