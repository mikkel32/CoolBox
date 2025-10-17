import os
import sys
import types
import tkinter as tk
import unittest
from typing import Any, cast
from unittest import mock

os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")


class _DummyWidget:
    def __init__(self, *args, **kwargs):
        pass

    def pack(self, *args, **kwargs):
        pass

    def grid(self, *args, **kwargs):
        pass

    def configure(self, *args, **kwargs):
        pass

    def destroy(self):
        pass

    def bind(self, *args, **kwargs):
        pass


dummy_ctk_mod = types.ModuleType("customtkinter")
dummy_ctk = cast(Any, dummy_ctk_mod)
dummy_ctk.CTkTabview = _DummyWidget
dummy_ctk.CTkScrollableFrame = _DummyWidget
dummy_ctk.CTkButton = _DummyWidget
dummy_ctk.CTkFrame = _DummyWidget
dummy_ctk.StringVar = tk.StringVar
dummy_ctk.CTkEntry = _DummyWidget
dummy_ctk.CTkOptionMenu = _DummyWidget
dummy_ctk.BooleanVar = tk.BooleanVar
dummy_ctk.CTkLabel = _DummyWidget
dummy_ctk.CTkCheckBox = _DummyWidget
dummy_ctk.CTkTextbox = _DummyWidget
sys.modules.setdefault("customtkinter", dummy_ctk_mod)

from coolbox.ui.views.dialogs.force_quit import ForceQuitDialog


@unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
class TestForceQuitInterval(unittest.TestCase):
    def _dummy_app(self):
        class DummyApp:
            def __init__(self) -> None:
                self.window = tk.Tk()
                self.config = {}

            def register_dialog(self, dialog) -> None:  # pragma: no cover - stub
                pass

            def unregister_dialog(self, dialog) -> None:  # pragma: no cover - stub
                pass

            def get_icon_photo(self):  # pragma: no cover - stub
                return None

        return DummyApp()

    def test_auto_tune_called_and_cached(self) -> None:
        app = self._dummy_app()
        auto_mock = mock.MagicMock(return_value=(0.1, 0.05, 0.2))

        class DummyOverlay:
            auto_tune_interval = auto_mock

            def __init__(self, *a, **kw) -> None:
                pass

            def reset(self) -> None:
                pass

            def _refresh_window_cache(self, *a, **kw) -> None:
                pass

        listener = mock.MagicMock()
        with (
            mock.patch("coolbox.ui.views.dialogs.force_quit.prime_window_cache"),
            mock.patch("coolbox.ui.views.dialogs.force_quit.get_global_listener", return_value=listener),
            mock.patch("coolbox.ui.views.dialogs.force_quit.ClickOverlay", DummyOverlay),
            mock.patch.object(ForceQuitDialog, "_auto_refresh"),
        ):
            dialog = ForceQuitDialog(app)
            dialog.destroy()
            app.window.destroy()

        auto_mock.assert_called_once()
        self.assertEqual(app.config.get("kill_by_click_interval_calibrated"), 0.1)
        self.assertEqual(app.config.get("kill_by_click_min_interval_calibrated"), 0.05)
        self.assertEqual(app.config.get("kill_by_click_max_interval_calibrated"), 0.2)

    def test_auto_tune_skipped_when_cached(self) -> None:
        app = self._dummy_app()
        app.config = {
            "kill_by_click_interval_calibrated": 0.1,
            "kill_by_click_min_interval_calibrated": 0.05,
            "kill_by_click_max_interval_calibrated": 0.2,
        }

        auto_mock = mock.MagicMock(return_value=(0.2, 0.1, 0.4))

        class DummyOverlay:
            auto_tune_interval = auto_mock

            def __init__(self, *a, **kw) -> None:
                self.args = kw

            def reset(self) -> None:
                pass

            def _refresh_window_cache(self, *a, **kw) -> None:
                pass

        listener = mock.MagicMock()
        with (
            mock.patch("coolbox.ui.views.dialogs.force_quit.prime_window_cache"),
            mock.patch("coolbox.ui.views.dialogs.force_quit.get_global_listener", return_value=listener),
            mock.patch("coolbox.ui.views.dialogs.force_quit.ClickOverlay", DummyOverlay),
            mock.patch.object(ForceQuitDialog, "_auto_refresh"),
        ):
            dialog = ForceQuitDialog(app)
            overlay_args = dialog._overlay
            dialog.destroy()
            app.window.destroy()

        auto_mock.assert_not_called()
        self.assertEqual(overlay_args.interval, 0.1)
        self.assertEqual(overlay_args.min_interval, 0.05)
        self.assertEqual(overlay_args.max_interval, 0.2)
