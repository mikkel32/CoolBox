import os
import unittest
from coolbox.app import CoolBoxApp
from coolbox.ui.views.quick_settings import QuickSettingsDialog


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


if __name__ == "__main__":
    unittest.main()
