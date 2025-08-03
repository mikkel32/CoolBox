import os
import unittest
import tkinter as tk
from unittest.mock import patch

from src.views.click_overlay import ClickOverlay


@unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
class TestClickOverlayDelay(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()

    def tearDown(self) -> None:
        self.root.destroy()

    def _create_overlay(self) -> ClickOverlay:
        with patch("src.views.click_overlay.is_supported", return_value=False), patch(
            "src.views.click_overlay.make_window_clickthrough", return_value=False
        ):
            overlay = ClickOverlay(self.root)
        self.addCleanup(overlay.destroy)
        return overlay

    def test_next_delay_clamped_after_high_frame_time(self) -> None:
        overlay = self._create_overlay()
        overlay.avg_frame_ms = 1000.0
        delay = overlay._next_delay()
        self.assertEqual(delay, int(overlay.min_interval * 1000))

    def test_next_delay_consistent_with_high_frame_time(self) -> None:
        overlay = self._create_overlay()
        overlay.avg_frame_ms = 1000.0
        first = overlay._next_delay()
        overlay._velocity = 500.0
        second = overlay._next_delay()
        self.assertEqual(first, int(overlay.min_interval * 1000))
        self.assertEqual(second, int(overlay.min_interval * 1000))

    def test_next_delay_respects_interval_bounds(self) -> None:
        overlay = self._create_overlay()
        overlay.min_interval = 0.01
        overlay.max_interval = 0.05
        overlay.interval = 0.2
        overlay._velocity = 0.0
        delay = overlay._next_delay()
        self.assertEqual(delay, int(overlay.max_interval * 1000))

    def test_retune_interval_respects_bounds(self) -> None:
        overlay = self._create_overlay()
        overlay.min_interval = 0.01
        overlay.max_interval = 0.05
        overlay.avg_frame_ms = 1000.0
        overlay._retune_interval()
        self.assertEqual(overlay.interval, overlay.max_interval)
        self.assertEqual(overlay.min_interval, 0.01)
        self.assertEqual(overlay.max_interval, 0.05)
        overlay.avg_frame_ms = 1.0
        overlay._retune_interval()
        self.assertEqual(overlay.interval, overlay.min_interval)


if __name__ == "__main__":
    unittest.main()
