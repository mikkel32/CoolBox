"""Basic application tests."""

import os
import unittest

from src.app import CoolBoxApp
from src.components.sidebar import COLLAPSED_WIDTH, EXPANDED_WIDTH


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
        # process pending animation events
        for _ in range(10):
            app.window.update()
        self.assertNotEqual(app.sidebar.collapsed, initial)
        # sidebar width should match the expected collapsed/expanded size
        expected_width = COLLAPSED_WIDTH if app.sidebar.collapsed else EXPANDED_WIDTH
        self.assertEqual(int(app.sidebar.cget("width")), expected_width)
        self.assertEqual(app.config.get("sidebar_collapsed"), app.sidebar.collapsed)
        expected = "▶" if app.sidebar.collapsed else "◀"
        self.assertEqual(app.sidebar.collapse_btn.cget("text"), expected)
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_sidebar_auto_resize(self) -> None:
        app = CoolBoxApp()
        app.window.geometry("500x600")
        app.window.update()
        self.assertTrue(app.sidebar.collapsed)
        # config should not persist auto-collapsed state
        self.assertFalse(app.config.get("sidebar_collapsed"))
        app.window.geometry("1200x800")
        app.window.update()
        self.assertFalse(app.sidebar.collapsed)
        self.assertFalse(app.config.get("sidebar_collapsed"))
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_sidebar_initial_state_large_window(self) -> None:
        app = CoolBoxApp()
        app.window.update()
        self.assertFalse(app.sidebar.collapsed)
        self.assertEqual(int(app.sidebar.cget("width")), EXPANDED_WIDTH)
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_sidebar_tooltips_show_and_hide(self) -> None:
        app = CoolBoxApp()
        app.sidebar.set_collapsed(True)
        tooltip = app.sidebar._tooltips["home"]
        tooltip.show(100, 100)
        app.window.update()
        self.assertTrue(tooltip.winfo_viewable())
        tooltip.hide()
        app.window.update()
        self.assertFalse(tooltip.winfo_viewable())
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_toolbar_tooltips_show_and_hide(self) -> None:
        app = CoolBoxApp()
        # Use the first created tooltip
        tooltip = app.toolbar._tooltips[0]
        tooltip.show(50, 50)
        app.window.update()
        self.assertTrue(tooltip.winfo_viewable())
        tooltip.hide()
        app.window.update()
        self.assertFalse(tooltip.winfo_viewable())
        app.destroy()


if __name__ == "__main__":
    unittest.main()
