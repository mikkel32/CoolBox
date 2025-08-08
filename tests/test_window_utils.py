import sys
import time
import unittest
from typing import Callable
from unittest import mock

from src.utils.window_utils import (
    WindowInfo,
    get_active_window,
    get_window_under_cursor,
    has_active_window_support,
    has_cursor_window_support,
    filter_windows_at,
)


class TestWindowUtils(unittest.TestCase):
    def setUp(self):
        from src.utils import window_utils as wu

        wu._TRANSIENT_PIDS.clear()
        wu._MIN_WINDOW_WIDTH = 0
        wu._MIN_WINDOW_HEIGHT = 0
        wu._CFG_LOADED = True

    def test_get_active_window(self):
        info = get_active_window()
        self.assertIsInstance(info, WindowInfo)
        self.assertTrue(hasattr(info, "title"))
        self.assertTrue(hasattr(info, "handle"))
        self.assertTrue(hasattr(info, "icon"))

    def test_get_window_under_cursor(self):
        info = get_window_under_cursor()
        self.assertIsInstance(info, WindowInfo)
        self.assertTrue(hasattr(info, "title"))
        self.assertTrue(hasattr(info, "handle"))
        self.assertTrue(hasattr(info, "icon"))

    def test_get_window_under_cursor_no_match_mac(self):
        from src.utils import window_utils as wu

        fake_quartz = type(
            "Q",
            (),
            {
                "CGEventCreate": lambda _n: object(),
                "CGEventGetLocation": lambda _e: type("L", (), {"x": 100, "y": 100})(),
                "CGWindowListCopyWindowInfo": lambda _opt, _id: [
                    {"kCGWindowBounds": {"X": 0, "Y": 0, "Width": 10, "Height": 10}}
                ],
                "kCGWindowListOptionOnScreenOnly": 0,
                "kCGNullWindowID": 0,
            },
        )

        with (
            mock.patch.object(wu.sys, "platform", "darwin"),
            mock.patch.dict(sys.modules, {"Quartz": fake_quartz}),
        ):
            info = wu.get_window_under_cursor()
        self.assertEqual(info, wu.WindowInfo(None))

    def test_get_window_under_cursor_malformed_output(self):
        from src.utils import window_utils as wu

        fake_info = "WINDOW=0x1\nBADLINE\nEXTRA=foo=bar\n"
        geom_out = (
            "Absolute upper-left X: 1\n"
            "Absolute upper-left Y: 2\n"
            "Width: 3\n"
            "Height: 4\n"
        )

        with (
            mock.patch.object(wu.sys, "platform", "linux"),
            mock.patch.object(wu, "_X_DISPLAY", None),
            mock.patch.object(wu.shutil, "which", return_value="/usr/bin/true"),
            mock.patch.object(
                wu.subprocess,
                "check_output",
                side_effect=[
                    fake_info,
                    "_NET_WM_PID(CARDINAL) = 5\n",
                    geom_out,
                    'WM_NAME(STRING) = "t"\n',
                ],
            ),
        ):
            info = wu.get_window_under_cursor()

        self.assertEqual(info.pid, 5)
        self.assertEqual(info.rect, (1, 2, 3, 4))
        self.assertEqual(info.title, "t")

    def test_get_window_at_no_match_mac(self):
        from src.utils import window_utils as wu

        fake_quartz = type(
            "Q",
            (),
            {
                "CGWindowListCopyWindowInfo": lambda _opt, _id: [
                    {"kCGWindowBounds": {"X": 0, "Y": 0, "Width": 10, "Height": 10}}
                ],
                "kCGWindowListOptionOnScreenOnly": 0,
                "kCGNullWindowID": 0,
            },
        )

        with (
            mock.patch.object(wu.sys, "platform", "darwin"),
            mock.patch.dict(sys.modules, {"Quartz": fake_quartz}),
        ):
            info = wu.get_window_at(100, 100)
        self.assertEqual(info, wu.WindowInfo(None))

    def test_get_window_at_match_mac(self):
        from src.utils import window_utils as wu

        windows = [
            {"kCGWindowBounds": {"X": 0, "Y": 0, "Width": 5, "Height": 5}},
            {
                "kCGWindowBounds": {"X": 10, "Y": 10, "Width": 20, "Height": 20},
                "kCGWindowOwnerPID": 1,
                "kCGWindowName": "target",
            },
            {"kCGWindowBounds": {"X": 30, "Y": 30, "Width": 5, "Height": 5}},
        ]

        fake_quartz = type(
            "Q",
            (),
            {
                "CGWindowListCopyWindowInfo": lambda _opt, _id: windows,
                "kCGWindowListOptionOnScreenOnly": 0,
                "kCGNullWindowID": 0,
            },
        )

        with (
            mock.patch.object(wu.sys, "platform", "darwin"),
            mock.patch.dict(sys.modules, {"Quartz": fake_quartz}),
        ):
            info = wu.get_window_at(15, 15)
        self.assertEqual(info.pid, 1)
        self.assertEqual(info.rect, (10, 10, 20, 20))
        self.assertEqual(info.title, "target")

    def test_support_flags(self):
        self.assertIsInstance(has_active_window_support(), bool)
        self.assertIsInstance(has_cursor_window_support(), bool)

    def test_has_cursor_window_support_display_missing(self):
        from src.utils import window_utils as wu

        with (
            mock.patch.object(wu.sys, "platform", "linux"),
            mock.patch.dict(wu.os.environ, {}, clear=True),
            mock.patch.object(wu.shutil, "which", return_value="/usr/bin/true"),
        ):
            self.assertFalse(wu.has_cursor_window_support())

    def test_has_cursor_window_support_display_present(self):
        from src.utils import window_utils as wu

        with (
            mock.patch.object(wu.sys, "platform", "linux"),
            mock.patch.dict(wu.os.environ, {"DISPLAY": ":0"}, clear=True),
            mock.patch.object(wu.shutil, "which", return_value="/usr/bin/true"),
        ):
            self.assertTrue(wu.has_cursor_window_support())

    def test_list_windows_at(self):
        from src.utils.window_utils import list_windows_at

        wins = list_windows_at(0, 0)
        self.assertIsInstance(wins, list)
        for info in wins:
            self.assertIsInstance(info, WindowInfo)
            self.assertTrue(hasattr(info, "handle"))

    def test_list_windows_fast_path(self):
        from src.utils import window_utils as wu

        fake = wu.WindowInfo(1)
        with (
            mock.patch.object(wu, "get_window_at", return_value=fake) as gwa,
            mock.patch.object(wu, "_fallback_list_windows_at") as fallback,
        ):
            res = wu.list_windows_at(0, 0, 1)
        self.assertEqual(res, [fake])
        gwa.assert_called_once_with(0, 0)
        fallback.assert_not_called()

    def test_fallback_async_cache(self):
        from src.utils import window_utils as wu

        fake_old = WindowInfo(2, (0, 0, 1, 1), "old")
        wu._WINDOWS_CACHE = {"time": 0.0, "windows": [fake_old]}

        def fake_enum():
            time.sleep(0.1)
            return [WindowInfo(1, (0, 0, 1, 1), "new")]

        with (
            mock.patch.object(wu, "_refresh_windows", fake_enum),
            mock.patch.object(wu, "subscribe_window_change", return_value=None),
        ):
            start = time.time()
            res = wu._fallback_list_windows_at(0, 0)
            self.assertLess(time.time() - start, 0.05)
            self.assertEqual(res, [fake_old])
            time.sleep(0.15)
            res2 = wu._fallback_list_windows_at(0, 0)
            self.assertEqual(res2[0].pid, 1)

    def test_window_change_event_refreshes_cache(self):
        from src.utils import window_utils as wu

        fake_old = WindowInfo(1, (0, 0, 1, 1), "old")
        fake_new = WindowInfo(2, (0, 0, 1, 1), "new")
        callbacks: list[Callable[[], None]] = []

        def fake_subscribe(cb):
            callbacks.append(cb)
            return lambda: None

        wu._WINDOWS_CACHE = {"time": time.time(), "windows": [fake_old]}
        wu._WINDOWS_THREAD = None
        wu._WINDOWS_EVENT_UNSUB = None
        wu._WINDOWS_EVENTS_SUPPORTED = False
        wu._WINDOWS_REFRESH.clear()
        wu._RECENT_WINDOWS.clear()

        with (
            mock.patch.object(wu, "subscribe_window_change", fake_subscribe),
            mock.patch.object(wu, "_refresh_windows", lambda: [fake_new]),
        ):
            self.assertEqual(wu.list_windows_at(0, 0), [fake_old])
            callbacks[0]()
            time.sleep(0.1)
            self.assertEqual(wu.list_windows_at(0, 0), [fake_new])

    def test_filter_windows_at(self):
        wins = [
            WindowInfo(1, (0, 0, 5, 5), "a"),
            WindowInfo(2, (10, 10, 5, 5), "b"),
        ]
        res = filter_windows_at(1, 1, wins)
        self.assertEqual(res, [wins[0]])
        res2 = filter_windows_at(12, 12, wins)
        self.assertEqual(res2, [wins[1]])

    def test_filter_windows_skips_small_and_tooltip(self):
        from src.utils import window_utils as wu

        small = wu.WindowInfo(1, (0, 0, 5, 5), "tiny")
        normal = wu.WindowInfo(2, (0, 0, 50, 50), "normal")
        tooltip = wu.WindowInfo(3, (0, 0, 50, 50), "tooltip window")

        with mock.patch.object(wu, "_MIN_WINDOW_WIDTH", 10), mock.patch.object(
            wu, "_MIN_WINDOW_HEIGHT", 10
        ):
            wu._TRANSIENT_PIDS.clear()
            res = wu.filter_windows_at(1, 1, [small, normal])
            self.assertEqual(res, [normal])
            self.assertIn(1, wu._TRANSIENT_PIDS)

        wu._TRANSIENT_PIDS.clear()
        with mock.patch.object(wu, "_MIN_WINDOW_WIDTH", 0), mock.patch.object(
            wu, "_MIN_WINDOW_HEIGHT", 0
        ):
            res = wu.filter_windows_at(1, 1, [tooltip, normal])
            self.assertEqual(res, [normal])
            self.assertIn(3, wu._TRANSIENT_PIDS)

    def test_x11_shortcuts(self):
        from src.utils import window_utils as wu

        fake = WindowInfo(1, (0, 0, 10, 10), "t")
        pointer = type("P", (), {"root_x": 5, "root_y": 6})()

        with (
            mock.patch.object(wu, "_X_DISPLAY", object()),
            mock.patch.object(wu, "_X_ROOT", mock.Mock(query_pointer=lambda: pointer)),
        ):
            wu._WINDOWS_CACHE = {"time": time.time(), "windows": [fake]}
            self.assertEqual(get_window_under_cursor(), fake)
            self.assertEqual(wu.get_window_at(5, 6), fake)
            self.assertEqual(wu.list_windows_at(5, 6), [fake])

    def test_subscribe_active_window(self):
        from src.utils import window_utils as wu

        infos = [WindowInfo(1), WindowInfo(2)]

        def fake_get_active():
            return infos.pop(0) if infos else WindowInfo(2)

        received: list[WindowInfo] = []
        with (
            mock.patch.object(wu, "_get_active_window_uncached", side_effect=fake_get_active),
            mock.patch.object(wu, "_POLL_INTERVAL", 0.01),
        ):
            unsub = wu.subscribe_active_window(lambda info: received.append(info))
            time.sleep(0.05)
            unsub()
        self.assertGreaterEqual(len(received), 2)
        self.assertEqual(received[0].pid, 1)
        self.assertEqual(received[1].pid, 2)

    def test_recent_ring_buffer(self):
        from src.utils import window_utils as wu

        w1 = wu.WindowInfo(1, (0, 0, 1, 1), "a", handle=1)
        w2 = wu.WindowInfo(2, (0, 0, 1, 1), "b", handle=2)
        w3 = wu.WindowInfo(3, (0, 0, 1, 1), "c", handle=3)
        with mock.patch.object(wu, "_RECENT_MAX", 2), mock.patch.object(
            wu, "_close_window_handle"
        ) as close_mock:
            wu._RECENT_WINDOWS.clear()
            wu._remember_window(w1)
            wu._remember_window(w2)
            self.assertEqual([w1, w2], list(wu._RECENT_WINDOWS))
            wu._remember_window(w3)
            self.assertEqual([w2, w3], list(wu._RECENT_WINDOWS))
            close_mock.assert_called_once_with(w1)

    def test_cleanup_recent(self):
        from src.utils import window_utils as wu

        w1 = wu.WindowInfo(1, handle=1)
        w2 = wu.WindowInfo(2, handle=2)
        wu._RECENT_WINDOWS.clear()
        wu._remember_window(w1)
        wu._remember_window(w2)
        with mock.patch.object(wu, "_close_window_handle") as close_mock:
            wu._cleanup_recent({2})
            self.assertEqual([w2], list(wu._RECENT_WINDOWS))
            close_mock.assert_called_once_with(w1)


if __name__ == "__main__":
    unittest.main()
