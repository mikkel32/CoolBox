import unittest
from unittest import mock
import time

from src.utils.window_utils import (
    WindowInfo,
    get_active_window,
    get_window_under_cursor,
    has_active_window_support,
    has_cursor_window_support,
    filter_windows_at,
)


class TestWindowUtils(unittest.TestCase):
    def test_get_active_window(self):
        info = get_active_window()
        self.assertIsInstance(info, WindowInfo)
        self.assertTrue(hasattr(info, "title"))

    def test_get_window_under_cursor(self):
        info = get_window_under_cursor()
        self.assertIsInstance(info, WindowInfo)
        self.assertTrue(hasattr(info, "title"))

    def test_support_flags(self):
        self.assertIsInstance(has_active_window_support(), bool)
        self.assertIsInstance(has_cursor_window_support(), bool)

    def test_list_windows_at(self):
        from src.utils.window_utils import list_windows_at

        wins = list_windows_at(0, 0)
        self.assertIsInstance(wins, list)
        for info in wins:
            self.assertIsInstance(info, WindowInfo)

    def test_fallback_async_cache(self):
        from src.utils import window_utils as wu

        fake_old = WindowInfo(2, (0, 0, 1, 1), "old")
        wu._WINDOWS_CACHE = {"time": 0.0, "windows": [fake_old]}

        def fake_enum():
            time.sleep(0.1)
            return [WindowInfo(1, (0, 0, 1, 1), "new")]

        with mock.patch.object(wu, "_refresh_windows", fake_enum):
            start = time.time()
            res = wu._fallback_list_windows_at(0, 0)
            self.assertLess(time.time() - start, 0.05)
            self.assertEqual(res, [fake_old])
            time.sleep(0.15)
            res2 = wu._fallback_list_windows_at(0, 0)
            self.assertEqual(res2[0].pid, 1)

    def test_filter_windows_at(self):
        wins = [
            WindowInfo(1, (0, 0, 5, 5), "a"),
            WindowInfo(2, (10, 10, 5, 5), "b"),
        ]
        res = filter_windows_at(1, 1, wins)
        self.assertEqual(res, [wins[0]])
        res2 = filter_windows_at(12, 12, wins)
        self.assertEqual(res2, [wins[1]])

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


if __name__ == "__main__":
    unittest.main()
