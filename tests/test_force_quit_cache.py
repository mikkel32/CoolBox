import os
import tkinter as tk
import unittest
from unittest import mock

from src.views.force_quit_dialog import ForceQuitDialog


@unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
class TestForceQuitCache(unittest.TestCase):
    def test_primes_window_cache_once(self) -> None:
        class DummyApp:
            def __init__(self) -> None:
                self.window = tk.Tk()
                self.config = {}

            def register_dialog(self, dialog) -> None:
                pass

            def unregister_dialog(self, dialog) -> None:
                pass

            def get_icon_photo(self):
                return None

        app = DummyApp()
        with (
            mock.patch("src.views.force_quit_dialog.prime_window_cache") as prime_mock,
            mock.patch("src.utils.window_utils.prime_window_cache", prime_mock),
            mock.patch(
                "src.views.click_overlay.prime_window_cache", prime_mock, create=True
            ),
            mock.patch("src.views.click_overlay.ClickOverlay"),
            mock.patch.object(ForceQuitDialog, "_auto_refresh"),
        ):
            dialog = ForceQuitDialog(app)
            dialog.destroy()
            app.window.destroy()
        prime_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()

