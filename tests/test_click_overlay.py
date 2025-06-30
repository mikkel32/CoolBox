import os
import unittest
import tkinter as tk

from src.views.click_overlay import ClickOverlay


class TestClickOverlay(unittest.TestCase):
    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_overlay_creation(self) -> None:
        root = tk.Tk()
        overlay = ClickOverlay(root)
        self.assertIsInstance(overlay, tk.Toplevel)
        overlay.destroy()
        root.destroy()


if __name__ == "__main__":
    unittest.main()
