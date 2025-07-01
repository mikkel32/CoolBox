"""Basic application tests."""

import os
import unittest
import customtkinter as ctk
from unittest.mock import patch

from src.app import CoolBoxApp


class TestCoolBoxApp(unittest.TestCase):
    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_initial_view(self) -> None:
        app = CoolBoxApp()
        self.assertEqual(app.state.current_view, "home")
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_sidebar_tooltips_show_and_hide(self) -> None:
        app = CoolBoxApp()
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
    def test_open_force_quit_method(self) -> None:
        app = CoolBoxApp()
        app.open_force_quit()
        dialogs = [w for w in app.window.winfo_children() if isinstance(w, ctk.CTkToplevel)]
        self.assertTrue(dialogs)
        for d in dialogs:
            d.destroy()
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_force_quit_singleton(self) -> None:
        app = CoolBoxApp()
        app.open_force_quit()
        first = app.force_quit_window
        app.open_force_quit()
        second = app.force_quit_window
        self.assertIs(first, second)
        second.destroy()
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_open_security_center_method(self) -> None:
        app = CoolBoxApp()
        patches = [
            patch("src.views.security_dialog.list_open_ports", lambda: {}),
            patch("src.views.security_dialog.is_firewall_enabled", lambda: True),
            patch("src.views.security_dialog.is_defender_enabled", lambda: True),
            patch("src.views.security_dialog.SecurityDialog._schedule_refresh", lambda self: None),
            patch("src.utils.security.is_admin", lambda: True),
        ]
        for p in patches:
            p.start()
        app.open_security_center()
        dialogs = [w for w in app.window.winfo_children() if isinstance(w, ctk.CTkToplevel)]
        self.assertTrue(dialogs)
        for d in dialogs:
            d.destroy()
        for p in patches:
            p.stop()
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_security_center_singleton(self) -> None:
        app = CoolBoxApp()
        patches = [
            patch("src.views.security_dialog.list_open_ports", lambda: {}),
            patch("src.views.security_dialog.is_firewall_enabled", lambda: True),
            patch("src.views.security_dialog.is_defender_enabled", lambda: True),
            patch("src.views.security_dialog.SecurityDialog._schedule_refresh", lambda self: None),
            patch("src.utils.security.is_admin", lambda: True),
        ]
        for p in patches:
            p.start()
        app.open_security_center()
        first = app.security_center_window
        app.open_security_center()
        second = app.security_center_window
        self.assertIs(first, second)
        second.destroy()
        for p in patches:
            p.stop()
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
