import unittest
from unittest import mock

from src.utils.window_utils import (
    WindowInfo,
    get_active_window,
    get_window_under_cursor,
    has_active_window_support,
    has_cursor_window_support,
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

    def test_x11_shortcuts(self):
        from src.utils import window_utils as wu

        fake = WindowInfo(1, (0, 0, 10, 10), "t")
        pointer = type("P", (), {"root_x": 5, "root_y": 6})()

        with mock.patch.object(wu, "_X_DISPLAY", object()), \
            mock.patch.object(wu, "_X_ROOT", mock.Mock(query_pointer=lambda: pointer)), \
            mock.patch.object(wu, "_list_windows_x11", return_value=[fake]):
            self.assertEqual(get_window_under_cursor(), fake)
            self.assertEqual(wu.get_window_at(5, 6), fake)
            self.assertEqual(wu.list_windows_at(5, 6), [fake])


if __name__ == "__main__":
    unittest.main()
