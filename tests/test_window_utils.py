import unittest

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


if __name__ == "__main__":
    unittest.main()
