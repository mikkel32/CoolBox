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
        help=(
            "Refresh rate in seconds for the overlay. Overrides "
            "KILL_BY_CLICK_INTERVAL if provided."
        ),
    )
    args = parser.parse_args(argv)

    root = tk.Tk()
    root.withdraw()
    kwargs = {"skip_confirm": args.skip_confirm}
    if args.interval is not None:
        interval = args.interval
    else:
        try:
            interval = float(os.getenv("KILL_BY_CLICK_INTERVAL", str(KILL_BY_CLICK_INTERVAL)))
        except ValueError:
            interval = KILL_BY_CLICK_INTERVAL
    kwargs["interval"] = interval
    overlay = ClickOverlay(root, **kwargs)
    pid, title = overlay.choose()
    if pid is None:
        print("No window selected")
    else:
        print(f"{pid} {title or ''}")
    root.destroy()


if __name__ == "__main__":
    main()
