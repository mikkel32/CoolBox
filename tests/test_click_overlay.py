import os
import unittest
import tkinter as tk
from unittest.mock import patch

from src.views.click_overlay import ClickOverlay, WindowInfo


class TestClickOverlay(unittest.TestCase):
    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_creation(self) -> None:
        root = tk.Tk()
        overlay = ClickOverlay(root)
        self.assertIsInstance(overlay, tk.Toplevel)
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_click_refreshes_window_info(self) -> None:
        root = tk.Tk()
        overlay = ClickOverlay(root)

        info1 = WindowInfo(1, (0, 0, 10, 10), "One")
        info2 = WindowInfo(2, (10, 10, 20, 20), "Two")

        with patch("src.views.click_overlay.get_window_under_cursor") as gwuc:
            gwuc.side_effect = [info1, info2]
            overlay._update_rect()

            self.assertEqual(overlay.pid, 1)
            self.assertEqual(overlay.title_text, "One")

            # prevent destruction so we can inspect values
            overlay.close = lambda _e=None: None
            overlay._click()

        self.assertEqual(overlay.pid, 2)
        self.assertEqual(overlay.title_text, "Two")

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_query_ignores_own_window(self) -> None:
        root = tk.Tk()
        overlay = ClickOverlay(root)

        info_self = WindowInfo(overlay._own_pid, (0, 0, 10, 10), "Self")
        info_target = WindowInfo(123, (5, 5, 10, 10), "Target")

        with patch("src.views.click_overlay.get_window_under_cursor") as gwuc:
            gwuc.side_effect = [info_self, info_target]
            result = overlay._query_window()

        self.assertEqual(result.pid, 123)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_query_loops_until_foreign_window(self) -> None:
        root = tk.Tk()
        overlay = ClickOverlay(root)

        info_self = WindowInfo(overlay._own_pid, (0, 0, 5, 5), "Self")
        info_other = WindowInfo(321, (5, 5, 10, 10), "Other")

        with patch("src.views.click_overlay.get_window_under_cursor") as gwuc:
            gwuc.side_effect = [info_self, info_self, info_other]
            result = overlay._query_window()

        self.assertEqual(result.pid, 321)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_position_label_keeps_on_screen(self) -> None:
        root = tk.Tk()
        overlay = ClickOverlay(root)

        overlay.canvas.bbox = lambda _item: (0, 0, 20, 10)
        overlay.winfo_screenwidth = lambda: 100
        overlay.winfo_screenheight = lambda: 50
        overlay._position_label(95, 45, 100, 50)

        x, y = overlay.canvas.coords(overlay.label)
        self.assertLessEqual(x + 20, 100)
        self.assertLessEqual(y + 10, 50)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_probe_attempts_respected(self) -> None:
        root = tk.Tk()
        overlay = ClickOverlay(root, probe_attempts=3)

        info_self = WindowInfo(overlay._own_pid, (0, 0, 10, 10), "Self")
        info_other = WindowInfo(999, (5, 5, 10, 10), "Other")

        with patch("src.views.click_overlay.get_window_under_cursor") as gwuc:
            gwuc.side_effect = [info_self, info_self, info_self, info_other]
            result = overlay._query_window()

        self.assertEqual(result.pid, 999)
        self.assertEqual(gwuc.call_count, 4)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_crosshair_lines_follow_cursor(self) -> None:
        root = tk.Tk()
        overlay = ClickOverlay(root)

        overlay.winfo_pointerx = lambda: 40
        overlay.winfo_pointery = lambda: 30
        overlay.winfo_screenwidth = lambda: 100
        overlay.winfo_screenheight = lambda: 80
        overlay._query_window = lambda: WindowInfo(1, None, "")
        overlay._update_rect()

        self.assertEqual(overlay.canvas.coords(overlay.hline), [0.0, 30.0, 100.0, 30.0])
        self.assertEqual(overlay.canvas.coords(overlay.vline), [40.0, 0.0, 40.0, 80.0])

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_choose_sets_timeout(self) -> None:
        root = tk.Tk()
        overlay = ClickOverlay(root, timeout=1.5)

        calls: list[int | str] = []

        def fake_after(delay: int, func) -> str:
            calls.append(delay)
            return "id"

        def fake_after_cancel(ident: str) -> None:
            calls.append("cancel")

        overlay.after = fake_after
        overlay.after_cancel = fake_after_cancel
        overlay._update_rect = lambda e=None: None
        overlay.grab_set = lambda: None
        overlay.wait_window = lambda: None

        overlay.choose()
        self.assertEqual(calls[0], int(1.5 * 1000))

        overlay.close()
        self.assertIn("cancel", calls)

        overlay.destroy()
        root.destroy()


if __name__ == "__main__":
    unittest.main()
