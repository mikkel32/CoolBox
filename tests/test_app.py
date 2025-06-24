"""Basic application tests."""

import os
import unittest

from src.app import CoolBoxApp


class TestCoolBoxApp(unittest.TestCase):
    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_initial_view(self) -> None:
        app = CoolBoxApp()
        self.assertEqual(app.state.current_view, "home")
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_toggle_sidebar_updates_config(self) -> None:
        app = CoolBoxApp()
        initial = app.sidebar.collapsed
        app.toggle_sidebar()
        self.assertNotEqual(app.sidebar.collapsed, initial)
        self.assertEqual(app.config.get("sidebar_collapsed"), app.sidebar.collapsed)
        expected = "▶" if app.sidebar.collapsed else "◀"
        self.assertEqual(app.sidebar.collapse_btn.cget("text"), expected)
        app.destroy()


if __name__ == "__main__":
    unittest.main()
