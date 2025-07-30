import os
import time
import unittest
import tkinter as tk
from unittest.mock import patch

from src.views.click_overlay import ClickOverlay, WindowInfo


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
    def test_overlay_invisible_when_color_key_missing(self) -> None:
        root = tk.Tk()
        with (
            patch("src.views.click_overlay.is_supported", return_value=False),
            patch("src.views.click_overlay.set_window_colorkey", return_value=False),
        ):
            overlay = ClickOverlay(root)
        try:
            alpha = float(overlay.attributes("-alpha"))
        except Exception:
            alpha = 1.0
        self.assertEqual(alpha, 0.0)
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
            patch("src.views.click_overlay.get_window_under_cursor") as gwuc,
            patch(
                "src.views.click_overlay.make_window_clickthrough", return_value=False
            ),
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
    def test_query_window_uses_extra_attempts(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root, probe_attempts=1)

        info1 = WindowInfo(1, (0, 0, 5, 5), "one")
        info2 = WindowInfo(2, (0, 0, 5, 5), "two")

        with (
            patch("src.views.click_overlay.get_window_at") as gwa,
            patch("src.utils.scoring_engine.tuning.confidence_ratio", 2.0),
            patch("src.utils.scoring_engine.tuning.extra_attempts", 2),
        ):
            gwa.side_effect = [info1, info2, info2, info2]
            result = overlay._query_window_at(0, 0)

        self.assertEqual(result.pid, 2)
        self.assertEqual(gwa.call_count, 4)

        overlay.destroy()
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_query_window_uses_dominance_threshold(self) -> None:
        root = tk.Tk()
        with patch("src.views.click_overlay.is_supported", return_value=False):
            overlay = ClickOverlay(root, probe_attempts=1)

        info1 = WindowInfo(1, (0, 0, 5, 5), "one")
        info2 = WindowInfo(2, (0, 0, 5, 5), "two")

        with (
            patch("src.views.click_overlay.get_window_at") as gwa,
            patch.object(overlay, "_weighted_confidence") as wc,
            patch("src.utils.scoring_engine.tuning.confidence_ratio", 1.0),
            patch("src.utils.scoring_engine.tuning.dominance", 0.9),
            patch("src.utils.scoring_engine.tuning.extra_attempts", 2),
        ):
            gwa.side_effect = [info1, info2, info2]
            wc.side_effect = [
                (info1, 1.5, 0.4),
                (info2, 1.5, 0.95),
            ]
            result = overlay._query_window_at(0, 0)

        self.assertEqual(result.pid, 2)
        self.assertEqual(wc.call_count, 2)
        self.assertEqual(gwa.call_count, 3)

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


if __name__ == "__main__":
    unittest.main()
