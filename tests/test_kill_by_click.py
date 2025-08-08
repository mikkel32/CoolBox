import os
import sys
import threading
import time
import importlib.util
import pathlib
import types
import io
import subprocess
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch

os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")
sys.modules.setdefault("matplotlib", mock.Mock())
sys.modules.setdefault("matplotlib.pyplot", mock.Mock())
sys.modules.setdefault("matplotlib.backends", mock.Mock())
sys.modules.setdefault("matplotlib.backends.backend_tkagg", mock.Mock())
sys.modules.setdefault("matplotlib.figure", mock.Mock())
sys.modules.setdefault("PIL", mock.Mock())
sys.modules.setdefault("PIL.Image", mock.Mock())
sys.modules.setdefault("PIL.ImageTk", mock.Mock())
class _CTKStub(types.ModuleType):
    def __getattr__(self, name):  # pragma: no cover - simple stub
        return _CTkBase


class _CTkBase:
    pass


class _CTkToplevel(_CTkBase):
    pass


class _CTkFont:
    def __init__(self, *a, **k):
        pass

ctk_stub = _CTKStub("customtkinter")
ctk_stub.CTkBaseClass = _CTkBase
ctk_stub.CTkToplevel = _CTkToplevel
ctk_stub.CTkFont = _CTkFont
sys.modules.setdefault("customtkinter", ctk_stub)

import src  # type: ignore[import]
views_pkg = types.ModuleType("src.views")
views_pkg.__path__ = [str(pathlib.Path("src/views"))]
sys.modules.setdefault("src.views", views_pkg)

spec = importlib.util.spec_from_file_location(
    "src.views.force_quit_dialog",
    pathlib.Path("src/views/force_quit_dialog.py"),
)
force_quit_dialog = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(force_quit_dialog)  # type: ignore[attr-defined]
sys.modules["src.views.force_quit_dialog"] = force_quit_dialog
ForceQuitDialog = force_quit_dialog.ForceQuitDialog


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

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})

    with (
        patch.dict(os.environ, {"FORCE_QUIT_CLICK_SKIP_CONFIRM": "1"}),
        patch("src.views.force_quit_dialog.messagebox") as MB,
        patch("src.views.force_quit_dialog.psutil.pid_exists", return_value=True),
        patch("src.views.force_quit_dialog.psutil.Process") as Proc,
    ):
        dialog._configure_overlay()
        overlay.on_hover(789, "win")
        ctx = dialog._OverlayContext(dialog, overlay)
        ctx.__enter__()
        dialog._overlay_ctx = ctx
        Proc.return_value.create_time.return_value = 1.0
        Proc.return_value.cmdline.return_value = ["cmd"]
        Proc.return_value.exe.return_value = "/bin/foo"
        dialog._finish_kill_by_click(ctx, (789, "win", 1.0, ("cmd",), "/bin/foo"))
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
    dialog.force_kill = mock.Mock(return_value=False)
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
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = mock.Mock(
        side_effect=lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()
    )

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
    assert dialog.after.call_args_list[0].args[0] == 0

    assert overlay.close.called
    dialog.force_kill.assert_not_called()
    assert dialog._highlight_pid.call_args_list[0].args == (123, "proc")
    assert dialog._highlight_pid.call_args_list[-1].args == (None, None)
    overlay.apply_defaults.assert_called_once()
    overlay.reset.assert_called_once()
    dialog.deiconify.assert_called_once()


def test_kill_by_click_cancel_allows_retry() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = False
    dialog._watcher = mock.Mock()
    dialog._populate = mock.Mock()
    dialog.withdraw = mock.Mock()
    dialog.deiconify = mock.Mock()
    dialog.after_idle = mock.Mock()
    dialog._safe_pause = mock.Mock()
    dialog._safe_resume = mock.Mock()

    overlay = mock.Mock()
    overlay.canvas = mock.Mock()
    overlay.rect = object()
    overlay.hline = object()
    overlay.vline = object()
    overlay.label = object()
    overlay.reset = mock.Mock()
    overlay.apply_defaults = mock.Mock()

    blocker = threading.Event()

    def choose() -> tuple[int | None, str | None]:
        overlay.on_hover(111, "proc")
        blocker.wait()
        blocker.clear()
        return (None, None)

    overlay.choose.side_effect = choose

    def close_side_effect() -> None:
        blocker.set()

    overlay.close.side_effect = close_side_effect

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = mock.Mock(
        side_effect=lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()
    )

    with (
        patch.dict(os.environ, {"FORCE_QUIT_CLICK_SKIP_CONFIRM": "1"}),
        patch("src.views.force_quit_dialog.messagebox"),
    ):
        dialog._configure_overlay()
        dialog._kill_by_click()
        time.sleep(0.05)
        dialog.cancel_kill_by_click()
        if dialog._overlay_thread:
            dialog._overlay_thread.join(timeout=1)
        assert dialog._overlay_thread is None

        dialog._kill_by_click()
        blocker.set()
        if dialog._overlay_thread:
            dialog._overlay_thread.join(timeout=1)
        time.sleep(0.05)

    assert dialog.after.call_args_list[0].args[0] == 0

    assert overlay.choose.call_count >= 2
    assert overlay.reset.call_count >= 2


def test_kill_by_click_cancel_clears_thread_even_if_stuck() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = False
    dialog._watcher = mock.Mock()
    dialog._populate = mock.Mock()
    dialog.withdraw = mock.Mock()
    dialog.deiconify = mock.Mock()
    dialog.after_idle = mock.Mock()

    overlay = mock.Mock()
    overlay.canvas = mock.Mock()
    overlay.rect = object()
    overlay.hline = object()
    overlay.vline = object()
    overlay.label = object()
    overlay.reset = mock.Mock()
    overlay.apply_defaults = mock.Mock()

    blocker = threading.Event()

    def choose() -> tuple[int | None, str | None]:
        overlay.on_hover(111, "proc")
        blocker.wait()
        return (None, None)

    overlay.choose.side_effect = choose
    overlay.close.side_effect = lambda: None

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = mock.Mock(
        side_effect=lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()
    )

    with (
        patch.dict(os.environ, {"FORCE_QUIT_CLICK_SKIP_CONFIRM": "1"}),
        patch("src.views.force_quit_dialog.messagebox"),
    ):
        dialog._configure_overlay()
        dialog._kill_by_click()
        time.sleep(0.05)
        thread = dialog._overlay_thread
        assert thread is not None and thread.is_alive()
        dialog.cancel_kill_by_click()
        assert dialog._overlay_thread is None
        blocker.set()
        if thread.is_alive():
            thread.join(timeout=1)
    assert dialog.after.call_args_list[0].args[0] == 0

    overlay.close.assert_called_once()
    dialog.deiconify.assert_called_once()


def test_kill_by_click_reports_when_no_selection(capsys) -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
    dialog._watcher = mock.Mock()
    dialog._populate = mock.Mock()
    dialog.withdraw = mock.Mock()
    dialog.deiconify = mock.Mock()
    dialog.after_idle = mock.Mock()
    dialog.force_kill = mock.Mock(return_value=False)
    dialog._highlight_pid = mock.Mock()

    overlay = mock.Mock()
    overlay.canvas = mock.Mock()
    overlay.rect = object()
    overlay.hline = object()
    overlay.vline = object()
    overlay.label = object()
    overlay.reset = mock.Mock()
    overlay.apply_defaults = mock.Mock()
    overlay.close = mock.Mock()
    overlay.choose.return_value = (None, None)

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()
    with (
        patch("builtins.print") as mock_print,
        patch("src.views.force_quit_dialog.messagebox"),
    ):
        ctx = dialog._OverlayContext(dialog, overlay)
        ctx.__enter__()
        dialog._overlay_ctx = ctx
        dialog._finish_kill_by_click(ctx, (None, None, None, None, None))

    out = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
    assert "Kill by Click failed to return a process" in out
    assert '"hover_pid": null' in out
    overlay.close.assert_called_once()
    dialog.force_kill.assert_not_called()


def test_kill_by_click_skips_vanished_process() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
    dialog._watcher = mock.Mock()
    dialog._populate = mock.Mock()
    dialog.withdraw = mock.Mock()
    dialog.deiconify = mock.Mock()
    dialog.after_idle = mock.Mock()
    dialog.force_kill = mock.Mock(return_value=False)
    dialog._highlight_pid = mock.Mock()

    overlay = mock.Mock()
    overlay.canvas = mock.Mock()
    overlay.rect = object()
    overlay.hline = object()
    overlay.vline = object()
    overlay.label = object()
    overlay.reset = mock.Mock()
    overlay.apply_defaults = mock.Mock()

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()
    with (
        patch("src.views.force_quit_dialog.psutil.pid_exists", return_value=False),
        patch("src.views.force_quit_dialog.messagebox") as MB,
        patch("builtins.print") as mock_print,
    ):
        ctx = dialog._OverlayContext(dialog, overlay)
        ctx.__enter__()
        dialog._overlay_ctx = ctx
        dialog._finish_kill_by_click(ctx, (123, "gone", 1.0, ("cmd",), "/bin/old"))
        MB.showwarning.assert_called_once()

    out = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
    assert "Kill by Click target vanished" in out
    dialog.force_kill.assert_called_once()


def test_kill_by_click_skips_pid_reuse() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
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

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()
    with (
        patch("src.views.force_quit_dialog.psutil.pid_exists", return_value=True),
        patch("src.views.force_quit_dialog.psutil.Process") as Proc,
        patch("src.views.force_quit_dialog.messagebox") as MB,
        patch("builtins.print") as mock_print,
    ):
        Proc.return_value.create_time.return_value = 2.0
        Proc.return_value.cmdline.return_value = ["cmd"]
        Proc.return_value.exe.return_value = "/bin/original"
        ctx = dialog._OverlayContext(dialog, overlay)
        ctx.__enter__()
        dialog._overlay_ctx = ctx
        dialog._finish_kill_by_click(ctx, (123, "reused", 1.0, ("cmd",), "/bin/original"))
        MB.showwarning.assert_called_once()

    out = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
    assert "Kill by Click target changed" in out
    dialog.force_kill.assert_not_called()


def test_kill_by_click_skips_cmdline_change() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
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

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()
    with (
        patch("src.views.force_quit_dialog.psutil.pid_exists", return_value=True),
        patch("src.views.force_quit_dialog.psutil.Process") as Proc,
        patch("src.views.force_quit_dialog.messagebox") as MB,
        patch("builtins.print") as mock_print,
    ):
        Proc.return_value.create_time.return_value = 1.0
        Proc.return_value.cmdline.return_value = ["new"]
        Proc.return_value.exe.return_value = "/bin/exe"
        ctx = dialog._OverlayContext(dialog, overlay)
        ctx.__enter__()
        dialog._overlay_ctx = ctx
        dialog._finish_kill_by_click(ctx, (123, "changed", 1.0, ("old",), "/bin/exe"))
        MB.showwarning.assert_called_once()

    out = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
    assert "Kill by Click target changed" in out
    dialog.force_kill.assert_not_called()


def test_kill_by_click_skips_exe_change() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
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

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()
    with (
        patch("src.views.force_quit_dialog.psutil.pid_exists", return_value=True),
        patch("src.views.force_quit_dialog.psutil.Process") as Proc,
        patch("src.views.force_quit_dialog.messagebox") as MB,
        patch("builtins.print") as mock_print,
    ):
        Proc.return_value.create_time.return_value = 1.0
        Proc.return_value.cmdline.return_value = ["cmd"]
        Proc.return_value.exe.return_value = "/bin/new"
        ctx = dialog._OverlayContext(dialog, overlay)
        ctx.__enter__()
        dialog._overlay_ctx = ctx
        dialog._finish_kill_by_click(ctx, (123, "changed", 1.0, ("cmd",), "/bin/old"))
        MB.showwarning.assert_called_once()

    out = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
    assert "Kill by Click target changed" in out
    dialog.force_kill.assert_not_called()


def test_kill_by_click_skips_self() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
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
    overlay.close = mock.Mock()
    overlay.skip_confirm = True

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()
    with (
        patch("src.views.force_quit_dialog.messagebox") as MB,
        patch("builtins.print") as mock_print,
    ):
        ctx = dialog._OverlayContext(dialog, overlay)
        ctx.__enter__()
        dialog._overlay_ctx = ctx
        dialog._finish_kill_by_click(ctx, (os.getpid(), "self", None, None, None))
        MB.showwarning.assert_called_once()

    out = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
    assert "Kill by Click refused to terminate self" in out
    dialog.force_kill.assert_not_called()


def test_kill_by_click_handles_no_selection() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
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
    overlay.skip_confirm = True

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()
    with (
        patch("src.views.force_quit_dialog.messagebox") as MB,
        patch("builtins.print") as mock_print,
    ):
        ctx = dialog._OverlayContext(dialog, overlay)
        ctx.__enter__()
        dialog._overlay_ctx = ctx
        dialog._finish_kill_by_click(ctx, (None, None, None, None, None))
        MB.showwarning.assert_called_once()

    out = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
    assert "Kill by Click failed to return a process" in out
    overlay.close.assert_called_once()
    dialog.force_kill.assert_not_called()


def test_kill_by_click_reports_exception() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
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

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()
    with patch("builtins.print") as mock_print:
        ctx = dialog._OverlayContext(dialog, overlay)
        ctx.__enter__()
        dialog._overlay_ctx = ctx
        dialog._finish_kill_by_click(ctx, RuntimeError("boom"))

    out = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
    assert "Kill by Click raised an exception" in out
    assert "boom" in out
    dialog.force_kill.assert_not_called()


def test_finish_kill_by_click_ignores_stale_context() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
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

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()
    ctx = dialog._OverlayContext(dialog, overlay)
    ctx.__enter__()
    dialog._overlay_ctx = None
    with patch("builtins.print") as mock_print:
        dialog._finish_kill_by_click(ctx, (None, None, None, None, None))
    assert mock_print.call_count == 0
    dialog.force_kill.assert_not_called()


def test_kill_by_click_reports_when_kill_fails() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
    dialog._watcher = mock.Mock()
    dialog._populate = mock.Mock()
    dialog.withdraw = mock.Mock()
    dialog.deiconify = mock.Mock()
    dialog.after_idle = mock.Mock()
    dialog.force_kill = mock.Mock(return_value=False)
    dialog._highlight_pid = mock.Mock()

    overlay = mock.Mock()
    overlay.canvas = mock.Mock()
    overlay.rect = object()
    overlay.hline = object()
    overlay.vline = object()
    overlay.label = object()
    overlay.reset = mock.Mock()
    overlay.apply_defaults = mock.Mock()

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()
    with (
        patch.dict(os.environ, {"FORCE_QUIT_CLICK_SKIP_CONFIRM": "1"}),
        patch("src.views.force_quit_dialog.messagebox") as MB,
        patch("builtins.print") as mock_print,
        patch("src.views.force_quit_dialog.psutil.pid_exists", return_value=True),
        patch("src.views.force_quit_dialog.psutil.Process") as Proc,
    ):
        ctx = dialog._OverlayContext(dialog, overlay)
        ctx.__enter__()
        dialog._overlay_ctx = ctx
        Proc.return_value.create_time.return_value = 1.0
        Proc.return_value.cmdline.return_value = ["cmd"]
        Proc.return_value.exe.return_value = "/bin/bad"
        dialog._finish_kill_by_click(ctx, (321, "bad", 1.0, ("cmd",), "/bin/bad"))
        MB.showerror.assert_called_once()

    out = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
    assert "Kill by Click could not terminate process" in out
    assert '"pid": 321' in out


def test_force_kill_reports_when_process_resists(capsys) -> None:
    with (
        patch("src.views.force_quit_dialog.kill_process", return_value=False) as kp,
        patch(
            "src.views.force_quit_dialog.kill_process_tree",
            return_value=False,
        ) as kpt,
        patch("src.views.force_quit_dialog.psutil.pid_exists", return_value=True),
        patch("src.views.force_quit_dialog.psutil.Process") as Proc,
    ):
        proc = Proc.return_value
        proc.name.return_value = "angry"
        proc.status.return_value = "running"
        ok = ForceQuitDialog.force_kill(555)

    assert not ok
    captured = capsys.readouterr().err
    assert kp.called and kpt.called
    assert "force_kill failed" in captured
    assert '"pid": 555' in captured


def test_kill_by_click_watchdog_reports_timeout() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
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
    overlay.close = mock.Mock()
    def _reset() -> None:
        overlay._last_ping = time.monotonic()
        overlay._watchdog_misses = 0
    overlay.reset_watchdog = mock.Mock(side_effect=_reset)
    overlay.choose.side_effect = lambda: time.sleep(0.5) or (None, None)

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()

    with (
        patch("builtins.print") as mock_print,
        patch("src.views.force_quit_dialog.KILL_BY_CLICK_WATCHDOG", 0.05),
        patch("src.views.force_quit_dialog.KILL_BY_CLICK_WATCHDOG_MISSES", 2),
    ):
        dialog._kill_by_click()
        time.sleep(0.2)

    out = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
    assert "Kill by Click timed out" in out
    assert '"missed_heartbeats": 2' in out
    overlay.close.assert_called_once()
    dialog.force_kill.assert_not_called()
    thread = dialog._overlay_thread
    if thread and thread.is_alive():
        thread.join(timeout=1)


def test_kill_by_click_watchdog_ignores_recent_activity() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
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
    overlay.close = mock.Mock()
    def _reset() -> None:
        overlay._last_ping = time.monotonic()
        overlay._watchdog_misses = 0
    overlay.reset_watchdog = mock.Mock(side_effect=_reset)

    def choose() -> tuple[int | None, str | None]:
        for _ in range(5):
            overlay.reset_watchdog()
            time.sleep(0.02)
        return (None, None)

    overlay.choose.side_effect = choose

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()

    with (
        patch("builtins.print") as mock_print,
        patch("src.views.force_quit_dialog.KILL_BY_CLICK_WATCHDOG", 0.05),
        patch("src.views.force_quit_dialog.KILL_BY_CLICK_WATCHDOG_MISSES", 2),
    ):
        dialog._kill_by_click()
        thread = dialog._overlay_thread
        if thread:
            thread.join(timeout=1)
        time.sleep(0.1)

    out = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
    assert "Kill by Click timed out" not in out
    overlay.close.assert_called_once()
    dialog.force_kill.assert_not_called()


def test_kill_by_click_watchdog_requires_multiple_misses() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
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
    overlay.close = mock.Mock()
    def _reset() -> None:
        overlay._last_ping = time.monotonic()
        overlay._watchdog_misses = 0
    overlay.reset_watchdog = mock.Mock(side_effect=_reset)
    overlay.choose.side_effect = lambda: time.sleep(0.5) or (None, None)

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()

    with (
        patch("builtins.print"),
        patch("src.views.force_quit_dialog.KILL_BY_CLICK_WATCHDOG", 0.05),
        patch("src.views.force_quit_dialog.KILL_BY_CLICK_WATCHDOG_MISSES", 2),
    ):
        dialog._kill_by_click()
        time.sleep(0.07)
        overlay.close.assert_not_called()
        time.sleep(0.1)
        overlay.close.assert_called_once()
    thread = dialog._overlay_thread
    if thread and thread.is_alive():
        thread.join(timeout=1)


def test_kill_by_click_watchdog_separate_process() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
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
    overlay.close = mock.Mock()
    def _reset() -> None:
        overlay._last_ping = time.monotonic()
        overlay._watchdog_misses = 0
    overlay.reset_watchdog = mock.Mock(side_effect=_reset)
    overlay.choose.side_effect = lambda: time.sleep(0.5) or (None, None)

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": True})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()

    with (
        patch("src.views.force_quit_dialog.KILL_BY_CLICK_WATCHDOG", 0.05),
        patch("src.views.force_quit_dialog.KILL_BY_CLICK_WATCHDOG_MISSES", 2),
    ):
        dialog._kill_by_click()
        proc = dialog._overlay_watchdog_proc
        assert proc is not None
        assert proc.pid and proc.pid != os.getpid()
        assert isinstance(proc, subprocess.Popen)
        dialog.cancel_kill_by_click()


def test_kill_by_click_watchdog_disabled_without_developer_mode() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog._overlay_thread = None
    dialog.accent = "#f00"
    dialog.paused = True
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
    def _reset() -> None:
        overlay._last_ping = time.monotonic()
        overlay._watchdog_misses = 0
    overlay.reset_watchdog = mock.Mock(side_effect=_reset)
    overlay.choose.return_value = (None, None)

    dialog._overlay = overlay
    dialog.app = SimpleNamespace(config={"developer_mode": False})
    dialog.after = lambda delay, cb, *args: threading.Timer(delay / 1000.0, cb, args).start()

    dialog._kill_by_click()
    assert dialog._overlay_watchdog_proc is None
    if dialog._overlay_thread:
        dialog._overlay_thread.join(timeout=1)
