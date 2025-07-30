import os
import unittest

from src.app import CoolBoxApp
from src.views.force_quit_dialog import ForceQuitDialog


@unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
class TestForceQuitFPS(unittest.TestCase):
    def test_frame_delay_uses_refresh_rate(self):
        os.environ["COOLBOX_REFRESH_RATE"] = "72"
        app = CoolBoxApp()
        try:
            dialog = ForceQuitDialog(app)
            expected = max(1, int(1000 / 72))
            self.assertEqual(dialog.frame_delay, expected)
            dialog.destroy()
        finally:
            os.environ.pop("COOLBOX_REFRESH_RATE", None)
            app.destroy()

    def test_force_quit_fps_override(self):
        os.environ["FORCE_QUIT_FPS"] = "90"
        app = CoolBoxApp()
        try:
            dialog = ForceQuitDialog(app)
            expected = max(1, int(1000 / 90))
            self.assertEqual(dialog.frame_delay, expected)
            dialog.destroy()
        finally:
            os.environ.pop("FORCE_QUIT_FPS", None)
            app.destroy()


if __name__ == "__main__":
    unittest.main()
