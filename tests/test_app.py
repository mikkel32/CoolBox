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


if __name__ == "__main__":
    unittest.main()
