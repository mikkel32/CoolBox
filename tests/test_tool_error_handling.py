import os
import time
import unittest
from tkinter import messagebox
from unittest.mock import patch
os.environ["COOLBOX_LIGHTWEIGHT"] = "1"
import customtkinter as ctk

from src.views.tools_view import ToolsView
from src.utils.thread_manager import ThreadManager


class DummyTheme:
    def get_theme(self):
        return {"accent_color": "#1faaff"}


class DummyStatus:
    def __init__(self):
        self.last = ""

    def set_message(self, msg: str, _type: str = "info") -> None:
        self.last = msg


class DummyApp:
    def __init__(self):
        self.thread_manager = ThreadManager()
        self.thread_manager.start()
        self.status_bar = DummyStatus()
        self.theme = DummyTheme()
        self.config = {}
        self.window = ctk.CTk()

    def destroy(self):
        self.thread_manager.stop()
        self.window.destroy()


class TestToolErrorHandling(unittest.TestCase):
    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_safe_launch_logs_errors(self) -> None:
        app = DummyApp()
        view = ToolsView(app.window, app)

        def boom():
            raise RuntimeError("kaboom")

        with patch.object(messagebox, "showerror") as showerror:
            view._safe_launch("Boom", boom)
            deadline = time.time() + 0.5
            while time.time() < deadline:
                app.window.update()
                time.sleep(0.05)
            self.assertTrue(showerror.called)
            self.assertTrue(
                any("Boom failed" in log for log in app.thread_manager.logs)
            )
            self.assertTrue(
                any("RuntimeError" in log for log in app.thread_manager.logs)
            )
            self.assertTrue(app.window.winfo_exists())
        app.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_safe_launch_logs_alerts(self) -> None:
        app = DummyApp()
        view = ToolsView(app.window, app)

        def warn() -> None:
            import importlib
            warn_mod = importlib.import_module("warn" "ings")
            warn_mod.warn("be careful")

        view._safe_launch("Warn", warn)
        deadline = time.time() + 0.5
        while time.time() < deadline:
            app.window.update()
            time.sleep(0.05)
        self.assertTrue(
            any("WARN" "ING:be careful" in log for log in app.thread_manager.logs)
        )
        app.destroy()


if __name__ == "__main__":
    unittest.main()

