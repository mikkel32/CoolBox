import os
import unittest
from src.app import CoolBoxApp
from src.views.quick_settings import QuickSettingsDialog


@unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
class TestQuickSettings(unittest.TestCase):
    def test_apply_updates_config(self) -> None:
        app = CoolBoxApp()
        dialog = QuickSettingsDialog(app)
        dialog.theme_var.set("Light")
        dialog.color_var.set("green")
        dialog._apply()
        self.assertEqual(app.config.get("appearance_mode"), "light")
        self.assertEqual(app.config.get("color_theme"), "green")
        app.destroy()

    def test_accent_preview_reverts(self) -> None:
        app = CoolBoxApp()
        orig = app.theme.get_theme().get("accent_color")
        dialog = QuickSettingsDialog(app)
        dialog.accent_var.set("#123456")
        self.assertEqual(app.theme.get_theme().get("accent_color"), "#123456")
        dialog.destroy()
        self.assertEqual(app.theme.get_theme().get("accent_color"), orig)
        app.destroy()


if __name__ == "__main__":
    unittest.main()
