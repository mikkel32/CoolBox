"""Basic application tests."""

import os
import unittest
import customtkinter as ctk
from unittest.mock import patch

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
    def test_sidebar_manual_override_persists(self) -> None:
        app = CoolBoxApp()
        app.window.update()
        self.assertFalse(app.sidebar.collapsed)

        app.toggle_sidebar()
        for _ in range(10):
            app.window.update()
        self.assertTrue(app.sidebar.collapsed)

        app.window.geometry("500x600")
        app.window.update()
        self.assertTrue(app.sidebar.collapsed)

        app.window.geometry("1200x800")
        app.window.update()
        self.assertTrue(app.sidebar.collapsed)

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

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_menubar_toggle(self) -> None:
        app = CoolBoxApp()
        self.assertIsNotNone(app.menu_bar)
        app.config.set("show_menu", False)
        app.update_ui_visibility()
        self.assertIsNone(app.menu_bar)
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_menubar_recent_files(self) -> None:
        app = CoolBoxApp()
        app.config.add_recent_file("foo.txt")
        app.refresh_recent_files()
        menu = app.menu_bar.recent_menu
        labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)]
        self.assertIn("foo.txt", labels)
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_menubar_sync(self) -> None:
        app = CoolBoxApp()
        app.toggle_sidebar()
        self.assertEqual(app.menu_bar.sidebar_var.get(), not app.sidebar.collapsed)
        app.toggle_fullscreen()
        self.assertEqual(app.menu_bar.fullscreen_var.get(), app.window.attributes("-fullscreen"))
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_quick_settings_dialog(self) -> None:
        app = CoolBoxApp()
        app.menu_bar._open_quick_settings()
        dialogs = [w for w in app.window.winfo_children() if isinstance(w, ctk.CTkToplevel)]
        self.assertTrue(dialogs)
        for d in dialogs:
            d.destroy()
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_toolbar_quick_settings(self) -> None:
        app = CoolBoxApp()
        app.toolbar._open_quick_settings()
        dialogs = [w for w in app.window.winfo_children() if isinstance(w, ctk.CTkToplevel)]
        self.assertTrue(dialogs)
        for d in dialogs:
            d.destroy()
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_open_quick_settings_method(self) -> None:
        app = CoolBoxApp()
        app.open_quick_settings()
        dialogs = [w for w in app.window.winfo_children() if isinstance(w, ctk.CTkToplevel)]
        self.assertTrue(dialogs)
        for d in dialogs:
            d.destroy()
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_quick_settings_singleton(self) -> None:
        app = CoolBoxApp()
        app.open_quick_settings()
        first = app.quick_settings_window
        app.open_quick_settings()
        second = app.quick_settings_window
        self.assertIs(first, second)
        second.destroy()
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_tools_view_launch_vm_debug_open_code(self) -> None:
        app = CoolBoxApp()

        class DummyThread:
            def __init__(self, target=None, daemon=None):
                if target:
                    target()

            def start(self):
                pass

        with patch("src.views.tools_view.messagebox.askyesno", side_effect=[True, True]), \
             patch("src.utils.launch_vm_debug") as launch, \
             patch("threading.Thread", DummyThread):
            app.views["tools"]._launch_vm_debug()
            launch.assert_called_once_with(open_code=True)

        app.destroy()


if __name__ == "__main__":
    unittest.main()
