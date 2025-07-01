import os
import unittest
import tkinter as tk
from unittest.mock import patch

from src.views.click_overlay import ClickOverlay, WindowInfo


class TestClickOverlay(unittest.TestCase):
    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_creation(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)
        self.assertIsInstance(overlay, tk.Toplevel)
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_click_falls_back_to_last_info(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        target = WindowInfo(1, (0, 0, 10, 10), "Target")
        info_self = WindowInfo(overlay._own_pid, (5, 5, 10, 10), "Self")

        with (
            patch("src.views.click_overlay.get_window_under_cursor") as gwuc,
            patch("src.views.click_overlay.make_window_clickthrough", return_value=False),
        ):
            gwuc.side_effect = [target, info_self]
            overlay._update_rect()

            overlay.close = lambda _e=None: None
            overlay._on_click()

        self.assertEqual(overlay.pid, 1)
        self.assertEqual(overlay.title_text, "Target")

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_click_refreshes_window_info(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
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
            overlay._on_click()

        self.assertEqual(overlay.pid, 2)
        self.assertEqual(overlay.title_text, "Two")

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_on_click_uses_click_coordinates(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._cursor_x = 1
        overlay._cursor_y = 2
        overlay._click_x = 30
        overlay._click_y = 40

        with (
            patch("src.views.click_overlay.get_window_at") as gwa,
            patch("src.views.click_overlay.make_window_clickthrough", return_value=False),
        ):
            gwa.return_value = WindowInfo(7, (0, 0, 5, 5), "clicked")
            overlay.close = lambda _e=None: None
            overlay._on_click()
            gwa.assert_called_with(30, 40)

        self.assertEqual(overlay.pid, 7)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_query_ignores_own_window(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
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
        with patch("src.views.click_overlay.is_supported", return_value=False):
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
        with patch("src.views.click_overlay.is_supported", return_value=False):
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
        with patch("src.views.click_overlay.is_supported", return_value=False):
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
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._cursor_x = 40
        overlay._cursor_y = 30
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
        with patch("src.views.click_overlay.is_supported", return_value=True):
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
        overlay.wait_window = lambda: None
        with patch("src.views.click_overlay.capture_mouse") as cap:
            cm = cap.return_value
            cm.__enter__.return_value = None
            overlay.choose()
            cap.assert_called_once()
        self.assertEqual(calls[0], int(1.5 * 1000))

        overlay.close()
        self.assertIn("cancel", calls)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_choose_falls_back_without_hooks(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._update_rect = lambda e=None: None
        overlay.wait_window = lambda: None
        with (
            patch(
                "src.views.click_overlay.make_window_clickthrough",
                return_value=False,
            ),
            patch("src.views.click_overlay.capture_mouse") as cap,
        ):
            cap.return_value.__enter__.return_value = None
            overlay.choose()
            cap.assert_not_called()

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_choose_fallback_when_listener_fails(self) -> None:
        root = tk.Tk()
        with (
            patch("src.views.click_overlay.is_supported", return_value=True),
            patch("src.views.click_overlay.make_window_clickthrough", return_value=True),
        ):
            overlay = ClickOverlay(root)

        overlay._update_rect = lambda e=None: None
        overlay.wait_window = lambda: None
        with (
            patch("src.views.click_overlay.remove_window_clickthrough") as rm,
            patch("src.views.click_overlay.capture_mouse") as cap,
        ):
            cm = cap.return_value
            cm.__enter__.return_value = None
            overlay.choose()
            cap.assert_called_once()
            rm.assert_called_once_with(overlay)
            self.assertFalse(overlay._using_hooks)
            self.assertFalse(overlay._clickthrough)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_choose_uses_hooks_when_listener_starts(self) -> None:
        root = tk.Tk()
        with (
            patch("src.views.click_overlay.is_supported", return_value=True),
            patch("src.views.click_overlay.make_window_clickthrough", return_value=True),
        ):
            overlay = ClickOverlay(root)

        overlay._update_rect = lambda e=None: None
        overlay.wait_window = lambda: None
        with patch("src.views.click_overlay.capture_mouse") as cap:
            cm = cap.return_value
            cm.__enter__.return_value = object()
            overlay.choose()
            cap.assert_called_once()
            self.assertTrue(overlay._using_hooks)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_choose_starts_tracker_when_no_hooks(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay.wait_window = lambda: None
        overlay._update_rect = lambda e=None: None
        with (
            patch(
                "src.views.click_overlay.make_window_clickthrough",
                return_value=False,
            ),
            patch("src.views.click_overlay.capture_mouse") as cap,
            patch.object(overlay, "bind") as bind_mock,
        ):
            cap.return_value.__enter__.return_value = None
            overlay.choose()
            cap.assert_not_called()
            bind_mock.assert_any_call("<Motion>", overlay._queue_update)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_queue_update_records_coordinates(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay.after_idle = lambda cb: cb()
        overlay._process_update = unittest.mock.Mock()
        event = tk.Event()
        event.x_root = 12
        event.y_root = 34
        overlay._queue_update(event)

        self.assertEqual((overlay._cursor_x, overlay._cursor_y), (12, 34))
        overlay._process_update.assert_called_once()

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_on_move_schedules_update(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._queue_update = unittest.mock.Mock()
        overlay._on_move(55, 66)

        self.assertEqual((overlay._cursor_x, overlay._cursor_y), (55, 66))
        overlay._queue_update.assert_called_once()

        overlay.destroy()
        root.destroy()


if __name__ == "__main__":
    unittest.main()
