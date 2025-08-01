import os
import unittest
import tkinter as tk
from unittest.mock import patch

from src.views.click_overlay import ClickOverlay


@unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
class TestClickOverlayFPS(unittest.TestCase):
    def test_interval_uses_refresh_rate(self):
        os.environ["COOLBOX_REFRESH_RATE"] = "75"
        root = tk.Tk()
        try:
            with (
                patch("src.views.click_overlay.is_supported", return_value=False),
                patch("src.views.click_overlay.make_window_clickthrough", return_value=False),
            ):
                overlay = ClickOverlay(root)
            self.assertAlmostEqual(overlay.interval, 1 / 150)
            overlay.destroy()
        finally:
            os.environ.pop("COOLBOX_REFRESH_RATE", None)
            root.destroy()

    def test_interval_env_override(self):
        os.environ["KILL_BY_CLICK_INTERVAL"] = "0.01"
        root = tk.Tk()
        try:
            with (
                patch("src.views.click_overlay.is_supported", return_value=False),
                patch("src.views.click_overlay.make_window_clickthrough", return_value=False),
            ):
                overlay = ClickOverlay(root)
            self.assertEqual(overlay.interval, 0.01)
            overlay.destroy()
        finally:
            os.environ.pop("KILL_BY_CLICK_INTERVAL", None)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
