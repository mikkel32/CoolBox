import os
import threading
import time
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch

os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")

from src.views.force_quit_dialog import ForceQuitDialog  # noqa: E402


def test_kill_by_click_selects_and_kills_pid() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
    dialog._watcher = mock.Mock()
    dialog._populate = mock.Mock()
    dialog.withdraw = mock.Mock()
    dialog.deiconify = mock.Mock()
    dialog.after_idle = mock.Mock()
    dialog.force_kill = mock.Mock(return_value=True)
    dialog._highlight_pid = mock.Mock()

    overlay = mock.Mock()
    overlay.canvas = mock.Mock()
    overlay.rect = object()
    overlay.hline = object()
    overlay.vline = object()
    overlay.label = object()
    overlay.reset = mock.Mock()
    overlay.apply_defaults = mock.Mock()

    def choose_side_effect():
        overlay.on_hover(789, "win")
        return (789, "win")

    overlay.choose.side_effect = choose_side_effect
    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={})
    dialog.after = lambda delay, cb, *args: cb(*args)

    with (
        patch.dict(os.environ, {"FORCE_QUIT_CLICK_SKIP_CONFIRM": "1"}),
        patch("src.views.force_quit_dialog.messagebox") as MB,
    ):
        dialog._configure_overlay()
        dialog._kill_by_click()
        if dialog._overlay_thread:
            dialog._overlay_thread.join(timeout=1)
        MB.askyesno.assert_not_called()
        MB.showinfo.assert_called_once()
        dialog.force_kill.assert_called_once_with(789)

    assert dialog._highlight_pid.call_args_list[0].args == (789, "win")
    assert dialog._highlight_pid.call_args_list[-1].args == (None, None)
    overlay.apply_defaults.assert_called_once()
    overlay.reset.assert_called_once()


def test_kill_by_click_cancel_does_not_kill() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = False
    dialog._watcher = mock.Mock()
    dialog._populate = mock.Mock()
    dialog.withdraw = mock.Mock()
    dialog.deiconify = mock.Mock()
    dialog.after_idle = mock.Mock()
    dialog.force_kill = mock.Mock()
    dialog._highlight_pid = mock.Mock()

    overlay = mock.Mock()
    overlay.canvas = mock.Mock()
    overlay.rect = object()
    overlay.hline = object()
    overlay.vline = object()
    overlay.label = object()
    overlay.reset = mock.Mock()
    overlay.apply_defaults = mock.Mock()
    blocker = threading.Event()
    cancelled = {"flag": False}

    def choose() -> tuple[int | None, str | None]:
        overlay.on_hover(123, "proc")
        blocker.wait()
        if cancelled["flag"]:
            return (None, None)
        return (123, "proc")

    overlay.choose.side_effect = choose

    def close_side_effect() -> None:
        cancelled["flag"] = True
        blocker.set()

    overlay.close.side_effect = close_side_effect

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={})
    dialog.after = lambda delay, cb, *args: cb(*args)

    with (
        patch.dict(os.environ, {"FORCE_QUIT_CLICK_SKIP_CONFIRM": "1"}),
        patch("src.views.force_quit_dialog.messagebox"),
    ):
        dialog._configure_overlay()
        dialog._kill_by_click()
        time.sleep(0.05)
        dialog.cancel_kill_by_click()
        blocker.set()
        if dialog._overlay_thread:
            dialog._overlay_thread.join(timeout=1)

    overlay.close.assert_called_once()
    dialog.force_kill.assert_not_called()
    assert dialog._highlight_pid.call_args_list[0].args == (123, "proc")
    assert dialog._highlight_pid.call_args_list[-1].args == (None, None)
    overlay.apply_defaults.assert_called_once()
    overlay.reset.assert_called_once()
