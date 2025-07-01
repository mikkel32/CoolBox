#!/usr/bin/env python3
"""Select a window by clicking it and print the PID and title."""

import tkinter as tk
from src.views.click_overlay import ClickOverlay


def main() -> None:
    root = tk.Tk()
    root.withdraw()
    overlay = ClickOverlay(root)
    pid, title = overlay.choose()
    if pid is None:
        print("No window selected")
    else:
        print(f"{pid} {title or ''}")
    root.destroy()


if __name__ == "__main__":
    main()
