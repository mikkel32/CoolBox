#!/usr/bin/env python3
"""Select a window by clicking it and print the PID and title."""

import os
import argparse
import tkinter as tk
from src.views.click_overlay import ClickOverlay


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Select a window and output its PID")
    parser.add_argument(
        "--skip-confirm",
        action="store_true",
        help="Close immediately without verifying the click position",
    )
    args = parser.parse_args(argv)

    root = tk.Tk()
    root.withdraw()
    overlay = ClickOverlay(root, skip_confirm=args.skip_confirm)
    pid, title = overlay.choose()
    if pid is None:
        print("No window selected")
    else:
        print(f"{pid} {title or ''}")
    root.destroy()


if __name__ == "__main__":
    main()
