import os
import time
import unittest
os.environ["COOLBOX_LIGHTWEIGHT"] = "1"
import customtkinter as ctk

from src.views.home_view import HomeView
from src.utils.thread_manager import ThreadManager


class DummyTheme:
    def get_theme(self):
        return {"accent_color": "#1faaff"}


class DummyApp:
    def __init__(self):
        self.thread_manager = ThreadManager()
        self.thread_manager.start()
        self.theme = DummyTheme()
        self.config = {}
        self.status_bar = None
        self.window = ctk.CTk()

    def destroy(self):
        self.thread_manager.stop()
        self.window.destroy()


class TestHomeWatchdog(unittest.TestCase):
    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_watchdog_displays_log(self) -> None:
        app = DummyApp()
        view = HomeView(app.window, app)
        app.thread_manager.log_queue.put("ERROR:boom")
        app.thread_manager.log_queue.put("WARNING:uh oh")
        time.sleep(0.2)
        view._flush_logs()
        content = view.console.get("1.0", "end")
        self.assertIn("boom", content)
        self.assertIn("[WARNING] uh oh", content)
        app.destroy()


if __name__ == "__main__":
    unittest.main()
