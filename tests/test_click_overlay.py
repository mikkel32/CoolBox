import os
import time
import unittest
import threading
import tkinter as tk
from unittest.mock import patch
from concurrent.futures import Future

from src.views.click_overlay import (
    ClickOverlay,
    WindowInfo,
    COLORKEY_RECHECK_MS,
    OverlayState,
)


class TestClickOverlay(unittest.TestCase):
    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_creation(self) -> None:
        root = tk.Tk()
        with (
            patch("src.views.click_overlay.is_supported", return_value=False),
            patch(
                "src.views.click_overlay.get_active_window",
                return_value=WindowInfo(None),
            ),
        ):
            overlay = ClickOverlay(root)
        self.assertIsInstance(overlay, tk.Toplevel)
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_colorkey_attributes_initialized(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)
        self.assertFalse(overlay._colorkey_warning_shown)
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_env_sets_default_highlight(self) -> None:
        with patch.dict(os.environ, {"KILL_BY_CLICK_HIGHLIGHT": "green"}):
            root = tk.Tk()
            with patch("src.views.click_overlay.is_supported", return_value=False):
                overlay = ClickOverlay(root)
            color = overlay.canvas.itemcget(overlay.rect, "outline")
            self.assertEqual(color, "green")
            overlay.destroy()
            root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_uses_transparent_color_key(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)
        try:
            key = overlay.attributes("-transparentcolor")
        except Exception:
            key = None
        self.assertEqual(key, overlay.cget("bg"))
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_uses_color_key_with_hooks(self) -> None:
        root = tk.Tk()
        with (
            patch("src.views.click_overlay.is_supported", return_value=True),
            patch("src.views.click_overlay.make_window_clickthrough", return_value=True),
        ):
            overlay = ClickOverlay(root)
        try:
            key = overlay.attributes("-transparentcolor")
        except Exception:
            key = None
        self.assertEqual(key, overlay.cget("bg"))
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_normalizes_named_bg_to_hex(self) -> None:
        root = tk.Tk()
        root.configure(bg="red")
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)
        try:
            key = overlay.attributes("-transparentcolor")
        except Exception:
            key = None
        self.assertEqual(overlay.cget("bg"), "#ff0000")
        self.assertEqual(key, "#ff0000")
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_normalizes_system_color_to_hex(self) -> None:
        root = tk.Tk()
        root.configure(bg="SystemButtonFace")
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)
        try:
            key = overlay.attributes("-transparentcolor")
        except Exception:
            key = None
        self.assertTrue(overlay.cget("bg").startswith("#"))
        self.assertEqual(key, overlay.cget("bg"))
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_uses_crosshair_cursor(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)
        cursor = overlay.canvas.cget("cursor")
        self.assertEqual(cursor, "crosshair")
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_visible_when_color_key_missing(self) -> None:
        root = tk.Tk()
        with (
            patch("src.views.click_overlay.is_supported", return_value=False),
            patch("src.views.click_overlay.set_window_colorkey", return_value=False),
            patch("builtins.print") as mock_print,
        ):
            overlay = ClickOverlay(root)
        try:
            alpha = float(overlay.attributes("-alpha"))
        except Exception:
            alpha = 0.0
        self.assertGreater(alpha, 0.0)
        mock_print.assert_called()
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_visible_when_color_key_ignored(self) -> None:
        root = tk.Tk()

        def fake_colorkey(_win):
            return True

        with (
            patch("src.views.click_overlay.is_supported", return_value=False),
            patch("src.views.click_overlay.set_window_colorkey", side_effect=fake_colorkey),
        ):
            overlay = ClickOverlay(root)
        try:
            alpha = float(overlay.attributes("-alpha"))
        except Exception:
            alpha = 0.0
        self.assertGreater(alpha, 0.0)
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_accepts_uppercase_color_key(self) -> None:
        root = tk.Tk()

        def attributes_side_effect(self, *args):
            if args and args[0] == "-transparentcolor" and len(args) == 1:
                return self.cget("bg").upper()
            return tk.Toplevel.attributes(self, *args)

        with (
            patch("src.views.click_overlay.is_supported", return_value=False),
            patch.object(ClickOverlay, "attributes", new=attributes_side_effect),
        ):
            overlay = ClickOverlay(root)
        try:
            alpha = float(overlay.attributes("-alpha"))
        except Exception:
            alpha = 1.0
        self.assertEqual(alpha, 1.0)
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_colorkey_revalidation_throttled(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)
        try:
            overlay._colorkey_last_check = time.monotonic()
            with patch.object(overlay, "_ensure_colorkey") as mock:
                overlay._maybe_ensure_colorkey()
                mock.assert_not_called()
                overlay._bg_color = "#123456"
                overlay._maybe_ensure_colorkey()
                mock.assert_called_once()
                mock.reset_mock()
                overlay._colorkey_last_check -= (COLORKEY_RECHECK_MS + 1) / 1000
                overlay._maybe_ensure_colorkey()
                mock.assert_called_once()
        finally:
            overlay.destroy()
            root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_update_rect_skips_colorkey_check(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)
        try:
            with patch.object(overlay, "_maybe_ensure_colorkey") as mock:
                overlay._update_rect(WindowInfo(None))
                mock.assert_not_called()
        finally:
            overlay.destroy()
            root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_configure_bg_triggers_colorkey(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)
        try:
            with patch.object(overlay, "_maybe_ensure_colorkey") as mock:
                overlay.configure(bg="#123456")
                mock.assert_called_once()
        finally:
            overlay.destroy()
            root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_accepts_shorthand_color_key(self) -> None:
        root = tk.Tk()
        root.configure(bg="white")

        def attributes_side_effect(self, *args):
            if args and args[0] == "-transparentcolor" and len(args) == 1:
                return "#FFF"
            return tk.Toplevel.attributes(self, *args)

        with (
            patch("src.views.click_overlay.is_supported", return_value=False),
            patch.object(ClickOverlay, "attributes", new=attributes_side_effect),
        ):
            overlay = ClickOverlay(root)
        try:
            alpha = float(overlay.attributes("-alpha"))
        except Exception:
            alpha = 1.0
        self.assertEqual(alpha, 1.0)
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_visible_when_color_key_removed_after_map(self) -> None:
        root = tk.Tk()

        def attributes_side_effect(self, *args):
            if args and args[0] == "-transparentcolor" and len(args) == 1:
                attributes_side_effect.calls += 1
                if attributes_side_effect.calls == 1:
                    return self.cget("bg")
                return ""
            return tk.Toplevel.attributes(self, *args)

        attributes_side_effect.calls = 0

        with (
            patch("src.views.click_overlay.is_supported", return_value=False),
            patch.object(ClickOverlay, "attributes", new=attributes_side_effect),
            patch(
                "src.views.click_overlay.set_window_colorkey",
                side_effect=[True, False],
            ) as swc,
        ):
            overlay = ClickOverlay(root)
        self.assertEqual(swc.call_count, 2)
        try:
            alpha = float(overlay.attributes("-alpha"))
        except Exception:
            alpha = 0.0
        self.assertGreater(alpha, 0.0)
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_recovers_color_key_after_loss(self) -> None:
        root = tk.Tk()

        def attributes_side_effect(self, *args):
            if args and args[0] == "-transparentcolor" and len(args) == 1:
                attributes_side_effect.calls += 1
                if attributes_side_effect.calls == 1:
                    return self.cget("bg")
                if attributes_side_effect.calls == 2:
                    return ""
                return self.cget("bg")
            return tk.Toplevel.attributes(self, *args)

        attributes_side_effect.calls = 0

        with (
            patch("src.views.click_overlay.is_supported", return_value=False),
            patch.object(ClickOverlay, "attributes", new=attributes_side_effect),
            patch(
                "src.views.click_overlay.set_window_colorkey",
                side_effect=[True, True],
            ) as swc,
        ):
            overlay = ClickOverlay(root)
        self.assertEqual(swc.call_count, 2)
        try:
            alpha = float(overlay.attributes("-alpha"))
        except Exception:
            alpha = 1.0
        self.assertEqual(alpha, 1.0)
        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_click_falls_back_to_last_info(self) -> None:
        root = tk.Tk()
        with (
            patch("src.views.click_overlay.is_supported", return_value=False),
            patch(
                "src.views.click_overlay.get_active_window",
                return_value=WindowInfo(None),
            ),
        ):
            overlay = ClickOverlay(root)

        target = WindowInfo(1, (0, 0, 10, 10), "Target")
        info_self = WindowInfo(overlay._own_pid, (5, 5, 10, 10), "Self")

        with (
            patch.object(overlay, "_query_window_at") as gwuc,
            patch(
                "src.views.click_overlay.make_window_clickthrough", return_value=False
            ),
        ):
            gwuc.side_effect = [target, info_self]
            overlay._update_rect()
            root.update()

            overlay.close = lambda _e=None: None
            overlay._on_click()

        self.assertEqual(overlay.pid, 1)
        self.assertEqual(overlay.title_text, "Target")

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_click_refreshes_window_info(self) -> None:
        root = tk.Tk()
        with (
            patch("src.views.click_overlay.is_supported", return_value=False),
            patch(
                "src.views.click_overlay.get_active_window",
                return_value=WindowInfo(None),
            ),
        ):
            overlay = ClickOverlay(root)

        info1 = WindowInfo(1, (0, 0, 10, 10), "One")
        info2 = WindowInfo(2, (10, 10, 20, 20), "Two")

        with patch.object(overlay, "_query_window_at") as gwuc:
            gwuc.side_effect = [info1, info2]
            overlay._update_rect()
            root.update()

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
    def test_update_rect_async_uses_worker(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)
        try:
            event = threading.Event()

            def slow_query(_x: int, _y: int) -> WindowInfo:
                event.set()
                time.sleep(0.05)
                return WindowInfo(99, (0, 0, 1, 1), "async")

            with patch.object(overlay, "_query_window_at", side_effect=slow_query):
                overlay._update_rect()
                self.assertIsNone(overlay.pid)
                event.wait(1.0)
                root.update()
                self.assertEqual(overlay.pid, 99)
        finally:
            overlay.destroy()
            root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_stale_async_results_ignored(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)
        try:
            overlay.after = lambda _ms, cb: cb()
            futures: list[Future] = []

            def fake_submit(fn):
                fut: Future = Future()
                futures.append(fut)
                return fut

            overlay._executor.submit = fake_submit  # type: ignore[assignment]

            overlay._update_rect()
            overlay._update_rect()

            futures[1].set_result(WindowInfo(2))
            futures[0].set_result(WindowInfo(1))

            self.assertEqual(overlay.pid, 2)
        finally:
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
            patch(
                "src.views.click_overlay.make_window_clickthrough", return_value=False
            ),
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

        with (
            patch("src.views.click_overlay.get_window_at") as gwa,
            patch("src.views.click_overlay.list_windows_at") as lwa,
        ):
            gwa.return_value = info_self
            lwa.return_value = [info_self, info_target]
            result = overlay._query_window()

        self.assertEqual(result.pid, 123)
        self.assertEqual(gwa.call_count, 1)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_query_single_probe(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay.state = OverlayState.HOOKED

        with (
            patch.object(
                overlay.engine.tracker,
                "best_with_confidence",
                return_value=(None, 0.0),
            ),
            patch.object(
                overlay,
                "_probe_point",
                return_value=WindowInfo(321, (0, 0, 5, 5), "Other"),
            ) as probe,
        ):
            result = overlay._query_window_at(0, 0)
            probe.assert_called_once()

        self.assertEqual(result.pid, 321)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_query_uses_cached_result_when_confident(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay.state = OverlayState.HOOKED
        cached = WindowInfo(7, (0, 0, 5, 5), "cached")
        overlay._cached_info = cached

        with (
            patch.object(
                overlay.engine.tracker,
                "best_with_confidence",
                return_value=(cached, overlay.engine.tuning.confidence_ratio + 1),
            ),
            patch.object(overlay, "_probe_point") as probe,
        ):
            info = overlay._query_window_at(0, 0)
            probe.assert_not_called()
        self.assertEqual(info.pid, 7)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_query_reprobes_when_confidence_low(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay.state = OverlayState.HOOKED
        cached = WindowInfo(7, (0, 0, 5, 5), "cached")
        overlay._cached_info = cached

        new_info = WindowInfo(8, (0, 0, 5, 5), "new")
        with (
            patch.object(
                overlay.engine.tracker,
                "best_with_confidence",
                return_value=(cached, overlay.engine.tuning.confidence_ratio - 0.1),
            ),
            patch.object(overlay, "_probe_point", return_value=new_info) as probe,
        ):
            info = overlay._query_window_at(0, 0)
            probe.assert_called_once()
        self.assertEqual(info.pid, 8)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_move_clears_cache(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay.state = OverlayState.HOOKED
        first = WindowInfo(1, (0, 0, 5, 5), "first")
        second = WindowInfo(2, (10, 10, 5, 5), "second")
        overlay._cached_info = first

        with (
            patch.object(
                overlay.engine.tracker,
                "best_with_confidence",
                return_value=(first, overlay.engine.tuning.confidence_ratio + 1),
            ),
            patch.object(overlay, "_probe_point", return_value=second) as probe,
        ):
            overlay._pending_move = (10, 10, time.time())
            overlay._handle_move()
            info = overlay._query_window_at(10, 10)
            self.assertEqual(info.pid, 2)
            probe.assert_called_once()

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
    def test_crosshair_lines_follow_cursor(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._cursor_x = 40
        overlay._cursor_y = 30
        overlay.winfo_screenwidth = lambda: 100
        overlay.winfo_screenheight = lambda: 80
        overlay._update_rect(WindowInfo(1, None, ""))

        self.assertEqual(overlay.canvas.coords(overlay.hline), [0.0, 30.0, 100.0, 30.0])
        self.assertEqual(overlay.canvas.coords(overlay.vline), [40.0, 0.0, 40.0, 80.0])

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_choose_sets_timeout(self) -> None:
        root = tk.Tk()
        with (
            patch("src.views.click_overlay.is_supported", return_value=True),
            patch(
                "src.views.click_overlay.get_active_window",
                return_value=WindowInfo(None),
            ),
        ):
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
            patch(
                "src.views.click_overlay.make_window_clickthrough", return_value=True
            ),
            patch(
                "src.views.click_overlay.get_active_window",
                return_value=WindowInfo(None),
            ),
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
            patch(
                "src.views.click_overlay.make_window_clickthrough", return_value=True
            ),
            patch(
                "src.views.click_overlay.get_active_window",
                return_value=WindowInfo(None),
            ),
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
    def test_queue_update_tracks_motion(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay.after_idle = lambda cb: cb()
        overlay._process_update = unittest.mock.Mock()
        overlay._heatmap.update = unittest.mock.Mock()
        overlay._last_move_pos = (0, 0)
        overlay._last_move_time = time.time() - 0.1

        event = tk.Event()
        event.x_root = 20
        event.y_root = 10
        overlay._queue_update(event)

        self.assertEqual(overlay._path_history[-1], (20, 10))
        self.assertGreater(overlay._velocity, 0)
        overlay._heatmap.update.assert_called_once_with(20, 10)
        overlay._process_update.assert_called_once()

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_on_move_schedules_update(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay.after_idle = unittest.mock.Mock()
        overlay._on_move(55, 66)

        overlay.after_idle.assert_called_once_with(overlay._handle_move)
        self.assertEqual(overlay._pending_move[:2], (55, 66))

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_weighted_choice_prefers_active_pid(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._pid_history.extend([2, 2])
        overlay._info_history.extend([WindowInfo(2)])
        overlay._initial_active_pid = 1
        samples = [WindowInfo(2), WindowInfo(1)]

        with (
            patch("src.utils.scoring_engine.tuning.sample_weight", 1.0),
            patch("src.utils.scoring_engine.tuning.history_weight", 1.0),
            patch("src.views.click_overlay.ACTIVE_BONUS", 5.0),
        ):
            choice = overlay._weighted_choice(samples)

        self.assertEqual(choice.pid, 1)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_weighted_confidence_returns_probability(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        samples = [WindowInfo(3), WindowInfo(3), WindowInfo(3)]

        info, ratio, prob = overlay._weighted_confidence(samples)

        self.assertEqual(info.pid, 3)
        self.assertGreaterEqual(prob, 0.99)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_velocity_weight_reduces_sample_influence(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._pid_history.extend([2])
        overlay._info_history.extend([WindowInfo(2)])
        overlay._velocity = 100.0
        samples = [WindowInfo(1)]

        with (
            patch("src.utils.scoring_engine.tuning.sample_weight", 1.0),
            patch("src.utils.scoring_engine.tuning.history_weight", 1.0),
            patch("src.utils.scoring_engine.tuning.velocity_scale", 1.0),
        ):
            choice = overlay._weighted_choice(samples)

        self.assertEqual(choice.pid, 2)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_stability_weight_influences_choice(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._pid_history.extend([2])
        overlay._info_history.extend([WindowInfo(2)])
        overlay._pid_stability[2] = 3
        samples = [WindowInfo(1)]

        with (
            patch("src.utils.scoring_engine.tuning.sample_weight", 1.0),
            patch("src.utils.scoring_engine.tuning.history_weight", 1.0),
            patch("src.utils.scoring_engine.tuning.stability_weight", 2.0),
        ):
            choice = overlay._weighted_choice(samples)

        self.assertEqual(choice.pid, 2)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_stable_info_requires_threshold(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._info_history.extend([WindowInfo(1), WindowInfo(1), WindowInfo(1)])
        overlay._pid_stability[1] = 3

        with patch("src.utils.scoring_engine.tuning.stability_threshold", 2):
            info = overlay._stable_info()

        self.assertIsNotNone(info)
        self.assertEqual(info.pid, 1)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_center_weight_biases_selection(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._cursor_x = 5
        overlay._cursor_y = 5
        samples = [
            WindowInfo(1, (0, 0, 10, 10), "one"),
            WindowInfo(2, (20, 20, 10, 10), "two"),
        ]

        with (
            patch("src.utils.scoring_engine.tuning.sample_weight", 1.0),
            patch("src.utils.scoring_engine.tuning.history_weight", 0.0),
            patch("src.utils.scoring_engine.tuning.center_weight", 5.0),
        ):
            choice = overlay._weighted_choice(samples)

        self.assertEqual(choice.pid, 1)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_edge_penalty_discourages_borders(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._cursor_x = 0
        overlay._cursor_y = 5
        samples = [
            WindowInfo(1, (0, 0, 10, 10), "one"),
            WindowInfo(2, (20, 0, 10, 10), "two"),
        ]

        with (
            patch("src.utils.scoring_engine.tuning.sample_weight", 1.0),
            patch("src.utils.scoring_engine.tuning.history_weight", 0.0),
            patch("src.utils.scoring_engine.tuning.edge_penalty", 0.9),
            patch("src.utils.scoring_engine.tuning.edge_buffer", 2),
        ):
            choice = overlay._weighted_choice(samples)

        self.assertEqual(choice.pid, 2)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_velocity_scaled_stability(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._info_history.extend([WindowInfo(1)])
        overlay._pid_stability[1] = 3
        overlay._velocity = 2.0

        with (
            patch("src.utils.scoring_engine.tuning.stability_threshold", 2),
            patch("src.utils.scoring_engine.tuning.vel_stab_scale", 2.0),
        ):
            info = overlay._stable_info()

        self.assertIsNone(info)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_path_weight_favors_hovered_window(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._cursor_x = 5
        overlay._cursor_y = 5
        overlay._path_history.extend([(5, 5), (6, 6), (7, 7)])
        samples = [
            WindowInfo(1, (0, 0, 10, 10), "one"),
            WindowInfo(2, (20, 20, 10, 10), "two"),
        ]

        with (
            patch("src.utils.scoring_engine.tuning.sample_weight", 1.0),
            patch("src.utils.scoring_engine.tuning.history_weight", 0.0),
            patch("src.utils.scoring_engine.tuning.path_weight", 3.0),
        ):
            choice = overlay._weighted_choice(samples)

        self.assertEqual(choice.pid, 1)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_heatmap_weight_biases_selection(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._heatmap.region_score = lambda r: 5.0 if r and r[0] == 0 else 0.1
        samples = [
            WindowInfo(1, (0, 0, 10, 10), "one"),
            WindowInfo(2, (20, 20, 10, 10), "two"),
        ]

        with (
            patch("src.utils.scoring_engine.tuning.sample_weight", 1.0),
            patch("src.utils.scoring_engine.tuning.history_weight", 0.0),
            patch("src.utils.scoring_engine.tuning.heatmap_weight", 2.0),
        ):
            choice = overlay._weighted_choice(samples)

        self.assertEqual(choice.pid, 1)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_streak_weight_amplifies_current_pid(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._current_pid = 2
        overlay._current_streak = 3
        samples = [WindowInfo(1), WindowInfo(2)]

        with (
            patch("src.utils.scoring_engine.tuning.sample_weight", 1.0),
            patch("src.utils.scoring_engine.tuning.history_weight", 0.0),
            patch("src.utils.scoring_engine.tuning.streak_weight", 2.0),
        ):
            choice = overlay._weighted_choice(samples)

        self.assertEqual(choice.pid, 2)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_recency_weight_biases_recent_pid(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        now = time.time()
        overlay._tracker.last_seen = {1: now - 1, 2: now - 0.1}
        overlay._tracker.durations = {1: 0.5, 2: 0.5}
        samples = [WindowInfo(1), WindowInfo(2)]

        with patch("src.utils.scoring_engine.tuning.recency_weight", 5.0):
            choice = overlay._weighted_choice(samples)

        self.assertEqual(choice.pid, 2)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_duration_weight_biases_longest_pid(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        now = time.time()
        overlay._tracker.last_seen = {1: now, 2: now}
        overlay._tracker.durations = {1: 2.0, 2: 0.5}
        samples = [WindowInfo(1), WindowInfo(2)]

        with patch("src.utils.scoring_engine.tuning.duration_weight", 3.0):
            choice = overlay._weighted_choice(samples)

        self.assertEqual(choice.pid, 1)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_active_history_biases_recent_focus(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._active_history.extend([(1, 0.0), (2, 0.1)])
        samples = [WindowInfo(1), WindowInfo(2)]

        with (
            patch("src.utils.scoring_engine.tuning.active_history_weight", 2.0),
            patch("src.views.click_overlay.ACTIVE_HISTORY_DECAY", 1.0),
        ):
            choice = overlay._weighted_choice(samples)

        self.assertEqual(choice.pid, 2)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_velocity_smoothing_applied(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._last_move_pos = (0, 0)
        overlay._last_move_time = 0.0

        overlay.after_idle = lambda cb: cb()

        with (
            patch("src.views.click_overlay.time.time", side_effect=[0.1, 0.2]),
            patch("src.utils.scoring_engine.tuning.velocity_smooth", 0.5),
        ):
            overlay._on_move(10, 0)
            first = overlay._velocity
            overlay._on_move(20, 0)
            second = overlay._velocity

        self.assertGreater(first, 0)
        self.assertGreater(second, first)
        self.assertLess(second, first * 2)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_zorder_weight_biases_front_window(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._cursor_x = 10
        overlay._cursor_y = 10
        samples = [WindowInfo(1, (0, 0, 20, 20)), WindowInfo(2, (0, 0, 20, 20))]
        stack = [WindowInfo(2), WindowInfo(1)]

        with (
            patch("src.utils.scoring_engine.tuning.sample_weight", 0.0),
            patch("src.utils.scoring_engine.tuning.history_weight", 0.0),
            patch("src.utils.scoring_engine.tuning.zorder_weight", 5.0),
            patch("src.views.click_overlay.list_windows_at", return_value=stack),
        ):
            choice = overlay._weighted_choice(samples)

        self.assertEqual(choice.pid, 2)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_tracker_ratio_used_when_query_fails(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._click_x = 0
        overlay._click_y = 0

        with (
            patch.object(overlay, "_query_window_at", return_value=WindowInfo(None)),
            patch.object(overlay, "_stable_info", return_value=None),
            patch.object(
                overlay._tracker,
                "best_with_confidence",
                return_value=(WindowInfo(8), 3.0),
            ),
            patch("src.utils.scoring_engine.tuning.tracker_ratio", 2.0),
        ):
            overlay.close = lambda _e=None: None
            overlay._on_click()

        self.assertEqual(overlay.pid, 8)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_confirm_weight_updates_pid(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._click_x = 5
        overlay._click_y = 5

        with (
            patch.object(
                overlay,
                "_query_window_at",
                return_value=WindowInfo(1, (0, 0, 10, 10), "one"),
            ),
            patch.object(
                overlay,
                "_confirm_window",
                return_value=WindowInfo(2, (5, 5, 10, 10), "two"),
            ),
            patch("src.utils.scoring_engine.tuning.confirm_weight", 5.0),
        ):
            overlay.close = lambda _e=None: None
            overlay._on_click()

        self.assertEqual(overlay.pid, 2)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_gaze_duration_tracks_hover(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        seq = iter([0.0, 0.5, 1.0])

        def fake_monotonic() -> float:
            return next(seq)

        with patch(
            "src.views.click_overlay.time.monotonic", side_effect=fake_monotonic
        ):
            overlay._update_rect(WindowInfo(1))
            overlay._update_rect(WindowInfo(1))
            overlay._update_rect(WindowInfo(2))

        self.assertGreaterEqual(overlay._gaze_duration.get(1, 0.0), 0.5)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_gaze_weight_biases_selection(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay._gaze_duration = {1: 0.1, 2: 2.0}
        samples = [WindowInfo(1), WindowInfo(2)]

        with patch("src.utils.scoring_engine.tuning.gaze_weight", 5.0):
            choice = overlay._weighted_choice(samples)

        self.assertEqual(choice.pid, 2)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_query_stack_fallback_when_self(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        self_info = WindowInfo(overlay._own_pid)
        stack = [WindowInfo(2, (0, 0, 10, 10), "target"), self_info]

        with (
            patch("src.views.click_overlay.get_window_at", return_value=self_info),
            patch("src.views.click_overlay.list_windows_at", return_value=stack),
            patch(
                "src.views.click_overlay.make_window_clickthrough", return_value=False
            ),
            patch.object(
                overlay, "_weighted_confidence", return_value=(None, 1.0, 1.0)
            ),
        ):
            result = overlay._query_window_at(0, 0)

        self.assertEqual(result.pid, 2)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_query_refreshes_missing_geometry(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        info = WindowInfo(5, None, "target")
        with (
            patch("src.views.click_overlay.get_window_at", return_value=info),
            patch(
                "src.views.click_overlay.list_windows_at",
                return_value=[WindowInfo(5, (1, 1, 10, 10), "target")],
            ),
            patch(
                "src.views.click_overlay.make_window_clickthrough", return_value=False
            ),
            patch.object(
                overlay, "_weighted_confidence", return_value=(None, 1.0, 1.0)
            ),
        ):
            result = overlay._query_window_at(1, 1)

        self.assertEqual(result.rect, (1, 1, 10, 10))

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_query_nearby_pixel_fallback(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        target = WindowInfo(6, (1, 0, 10, 10), "target")

        def fake_get_window_at(px: int, py: int) -> WindowInfo:
            return WindowInfo(None) if (px, py) == (0, 0) else target

        with (
            patch(
                "src.views.click_overlay.get_window_at", side_effect=fake_get_window_at
            ),
            patch("src.views.click_overlay.list_windows_at", return_value=[target]),
            patch(
                "src.views.click_overlay.make_window_clickthrough", return_value=False
            ),
            patch.object(
                overlay, "_weighted_confidence", return_value=(None, 1.0, 1.0)
            ),
        ):
            overlay.NEAR_RADIUS = 1
            result = overlay._query_window_at(0, 0)

        self.assertEqual(result.pid, 6)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_update_rect_rehighlights_on_pid_change(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        overlay.after = lambda _delay, func: func()
        overlay.after_cancel = lambda _id: None
        overlay.winfo_screenwidth = lambda: 100
        overlay.winfo_screenheight = lambda: 100
        overlay.canvas.coords = unittest.mock.Mock()
        overlay.canvas.itemconfigure = unittest.mock.Mock()

        overlay._cursor_x = 5
        overlay._cursor_y = 5
        overlay._update_rect(WindowInfo(1, (0, 0, 10, 10), "one"))
        overlay.canvas.coords.reset_mock()

        overlay._update_rect(WindowInfo(1, (0, 0, 10, 10), "one"))
        same_calls = [
            c for c in overlay.canvas.coords.call_args_list if c.args[0] == overlay.rect
        ]
        overlay.canvas.coords.reset_mock()

        overlay._update_rect(WindowInfo(2, (0, 0, 10, 10), "two"))
        changed_calls = [
            c for c in overlay.canvas.coords.call_args_list if c.args[0] == overlay.rect
        ]

        self.assertEqual(len(same_calls), 0)
        self.assertEqual(len(changed_calls), 1)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_on_hover_callback_invoked(self) -> None:
        root = tk.Tk()
        calls: list[tuple[int | None, str | None]] = []
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(
                root, on_hover=lambda pid, title: calls.append((pid, title))
            )

        overlay._cursor_x = 1
        overlay._cursor_y = 1
        overlay._update_rect(WindowInfo(5, (0, 0, 5, 5), "foo"))

        self.assertIn((5, "foo"), calls)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_on_hover_not_called_when_window_unchanged(self) -> None:
        root = tk.Tk()
        calls: list[tuple[int | None, str | None]] = []
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(
                root, on_hover=lambda pid, title: calls.append((pid, title))
            )

        overlay._cursor_x = 1
        overlay._cursor_y = 1
        info = WindowInfo(5, (0, 0, 5, 5), "foo")
        overlay._update_rect(info)
        overlay._cursor_x = 2
        overlay._cursor_y = 2
        overlay._update_rect(info)

        self.assertEqual(calls, [(5, "foo")])

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_tracker_add_runs_off_thread(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root)

        main_thread = threading.get_ident()
        called: dict[str, int] = {}
        done = threading.Event()

        def fake_add(info, pid):  # type: ignore[unused-arg]
            called["worker"] = threading.get_ident()

        def cb(_=None):
            called["callback"] = threading.get_ident()
            done.set()

        overlay.engine.tracker.add = fake_add  # type: ignore[assignment]
        overlay._track_async(WindowInfo(1), cb)
        while not done.wait(0.01):
            root.update()

        self.assertNotEqual(called["worker"], main_thread)
        self.assertEqual(called["callback"], main_thread)

        overlay.destroy()
        root.destroy()


if __name__ == "__main__":
    unittest.main()
