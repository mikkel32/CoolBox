import os
import time
import unittest
import tkinter as tk
from unittest.mock import Mock, patch

os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")

from coolbox.ui.views.click_overlay import ClickOverlay, WindowInfo, PROBE_CACHE_TTL  # noqa: E402


class TestClickOverlayProbeTTL(unittest.TestCase):
    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_fast_cursor_expires_cache_quickly(self) -> None:
        root = tk.Tk()
        with (
            patch("coolbox.ui.views.click_overlay.is_supported", return_value=False),
            patch("coolbox.ui.views.click_overlay.subscribe_window_change", return_value=None),
            patch("coolbox.ui.views.click_overlay.get_active_window", return_value=WindowInfo(None)),
            patch("coolbox.ui.views.click_overlay.subscribe_active_window", return_value=None),
        ):
            overlay = ClickOverlay(root)
        try:
            overlay._window_cache_rect = (0, 0, 100, 100)
            overlay._window_cache_future = None

            now = time.monotonic()
            overlay._window_cache_time = now - PROBE_CACHE_TTL / 2
            overlay._pending_move = (10, 10, now)
            overlay._last_move_time = now - 0.1
            overlay._kf_x.update = Mock(return_value=(10, 0.0))
            overlay._kf_y.update = Mock(return_value=(10, 0.0))
            with patch.object(overlay, "_refresh_window_cache") as refresh:
                overlay._handle_move()
                slow_ttl = overlay._probe_cache_ttl
                self.assertFalse(refresh.called)

            now = time.monotonic()
            overlay._window_cache_time = now - PROBE_CACHE_TTL / 2
            overlay._pending_move = (20, 20, now)
            overlay._last_move_time = now - 0.1
            overlay._kf_x.update = Mock(return_value=(20, 200.0))
            overlay._kf_y.update = Mock(return_value=(20, 0.0))
            with patch.object(overlay, "_refresh_window_cache") as refresh:
                overlay._handle_move()
                fast_ttl = overlay._probe_cache_ttl
                self.assertTrue(refresh.called)

            self.assertLess(fast_ttl, slow_ttl)
        finally:
            overlay.destroy()
            root.destroy()
