import os
import unittest

from src.utils.ui import get_screen_refresh_rate

class TestScreenRefreshRate(unittest.TestCase):
    def test_env_override(self):
        os.environ["COOLBOX_REFRESH_RATE"] = "75"
        try:
            self.assertEqual(get_screen_refresh_rate(), 75)
        finally:
            os.environ.pop("COOLBOX_REFRESH_RATE", None)

if __name__ == "__main__":
    unittest.main()
