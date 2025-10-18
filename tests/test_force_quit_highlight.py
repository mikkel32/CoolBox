import os
import sys
import types
import pathlib
import unittest
from unittest import mock


class TestForceQuitHighlight(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")
        coolbox_pkg = types.ModuleType("coolbox")
        coolbox_pkg.__path__ = [
            str(pathlib.Path(__file__).resolve().parents[1] / "src" / "coolbox")
        ]
        views_pkg = types.ModuleType("coolbox.ui.views")
        views_pkg.__path__ = [
            str(pathlib.Path(__file__).resolve().parents[1] / "src" / "coolbox" / "views")
        ]
        modules = {
            "coolbox": coolbox_pkg,
            "coolbox.ui.views": views_pkg,
            "customtkinter": types.SimpleNamespace(
                CTk=object,
                CTkFrame=object,
                CTkButton=object,
                CTkLabel=object,
                CTkToplevel=object,
                StringVar=object,
            ),
            "coolbox.utils.window_utils": types.SimpleNamespace(
                WindowInfo=object,
                get_active_window=lambda: None,
                get_window_under_cursor=lambda *_a, **_k: None,
                has_active_window_support=lambda: False,
                has_cursor_window_support=lambda: False,
                prime_window_cache=lambda: None,
            ),
            "coolbox.utils.kill_utils": types.SimpleNamespace(
                kill_process=lambda *_a, **_k: None,
                kill_process_tree=lambda *_a, **_k: None,
            ),
            "coolbox.utils": types.SimpleNamespace(get_screen_refresh_rate=lambda: 60),
            "coolbox.utils.process_monitor": types.SimpleNamespace(
                ProcessEntry=object, ProcessWatcher=object
            ),
            "coolbox.ui.views.base_dialog": types.SimpleNamespace(BaseDialog=object),
            "coolbox.utils.color_utils": types.SimpleNamespace(
                hex_brightness=lambda c: c,
                lighten_color=lambda c, *_a: c,
                darken_color=lambda c, *_a: c,
            ),
            "coolbox.utils.mouse_listener": types.SimpleNamespace(
                get_global_listener=lambda: types.SimpleNamespace(start=lambda: None)
            ),
            "coolbox.ui.views.overlays.click_overlay": types.SimpleNamespace(
                ClickOverlay=object, KILL_BY_CLICK_INTERVAL=0.1
            ),
        }
        self.patcher = mock.patch.dict(sys.modules, modules)
        self.patcher.start()
        sys.modules.pop("coolbox.ui.views.dialogs.force_quit", None)
        from coolbox.ui.views.dialogs.force_quit import ForceQuitDialog
        self.ForceQuitDialog = ForceQuitDialog

    def tearDown(self) -> None:
        self.patcher.stop()
        sys.modules.pop("coolbox.ui.views.dialogs.force_quit", None)

    def test_highlight_pid_skips_duplicate_selection(self) -> None:
        dialog = self.ForceQuitDialog.__new__(self.ForceQuitDialog)
        tree = mock.Mock()
        tree.exists.return_value = True
        tree.selection.return_value = ("123",)
        dialog.tree = tree
        dialog._set_hover_row = mock.Mock()
        dialog._show_details = mock.Mock()

        dialog._highlight_pid(123)

        tree.selection_set.assert_not_called()
        tree.see.assert_not_called()
        dialog._show_details.assert_not_called()

    def test_repeated_hover_same_pid_no_update(self) -> None:
        dialog = self.ForceQuitDialog.__new__(self.ForceQuitDialog)
        tree = mock.Mock()
        tree.exists.return_value = True
        tree.selection.return_value = ("456",)
        dialog.tree = tree
        dialog._set_hover_row = mock.Mock()
        dialog._show_details = mock.Mock()

        dialog._highlight_pid(123)

        tree.see.assert_called_once_with("123")
        tree.selection_set.assert_called_once_with("123")
        dialog._show_details.assert_called_once()

        tree.selection.return_value = ("123",)
        tree.see.reset_mock()
        tree.selection_set.reset_mock()
        dialog._show_details.reset_mock()

        dialog._highlight_pid(123)

        tree.see.assert_not_called()
        tree.selection_set.assert_not_called()
        dialog._show_details.assert_not_called()
        self.assertEqual(dialog._set_hover_row.call_count, 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
