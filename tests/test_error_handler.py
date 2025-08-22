import os
import sys
import threading
import warnings
import subprocess
import json
import pytest
from types import SimpleNamespace

from src.app import error_handler as eh
from src.utils.logging_config import setup_logging


# Ensure lightweight mode so the GUI toolkit is not required
os.environ["COOLBOX_LIGHTWEIGHT"] = "1"


def test_warning_and_unraisable_capture(tmp_path, monkeypatch):
    """Warnings and unraisable exceptions should be recorded."""
    # Configure logging to a temporary file to ensure handlers exist
    setup_logging(log_file=str(tmp_path / "log.txt"))

    # Restore hooks after the test to avoid side effects
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(warnings, "showwarning", warnings.showwarning)
    monkeypatch.setattr(sys, "unraisablehook", sys.unraisablehook)

    eh.RECENT_ERRORS.clear()
    eh.RECENT_WARNINGS.clear()

    eh.install()

    warnings.warn("be careful", UserWarning)
    assert any("be careful" in w for w in eh.RECENT_WARNINGS)

    info = SimpleNamespace(
        exc_type=RuntimeError,
        exc_value=RuntimeError("boom"),
        exc_traceback=None,
        err_msg=None,
        object=None,
    )
    sys.unraisablehook(info)
    assert any("boom" in e for e in eh.RECENT_ERRORS)


def test_handle_exception_uses_dialog(monkeypatch):
    """``handle_exception`` should invoke the error dialog helper."""

    called = {}

    def fake_dialog(msg: str, details: str) -> None:
        called["msg"] = msg
        called["details"] = details

    monkeypatch.setattr(eh, "_show_error_dialog", fake_dialog)

    try:
        raise RuntimeError("kaboom")
    except RuntimeError as exc:
        eh.handle_exception(RuntimeError, exc, None)

    assert "kaboom" in called["msg"]
    assert "RuntimeError" in called["details"]
    assert "Location:" in called["details"]
    assert "Traceback:" in called["details"]


def test_error_dialog_creates_root_when_default_destroyed(monkeypatch):
    """If the default Tk root is unusable a new one should be created."""

    class DeadRoot:
        def winfo_exists(self):
            return False

        def wait_window(self, _):
            pass

    dead_root = DeadRoot()

    monkeypatch.setattr(eh, "tk", SimpleNamespace(_default_root=dead_root), raising=False)

    created = {}

    class NewRoot:
        def __init__(self):
            self.destroyed = False

        def withdraw(self):
            pass

        def wait_window(self, _):
            pass

        def destroy(self):
            self.destroyed = True

        def winfo_exists(self):
            return True

    new_root = NewRoot()

    def fake_ctk():
        created["called"] = True
        return new_root

    ctk_mod = SimpleNamespace(CTk=fake_ctk)
    monkeypatch.setitem(sys.modules, "customtkinter", ctk_mod)

    class FakeDialog:
        def __init__(self, master, message, details, log_file):
            pass

    mod = SimpleNamespace(ModernErrorDialog=FakeDialog)
    monkeypatch.setitem(sys.modules, "src.components.modern_error_dialog", mod)

    monkeypatch.setattr(eh, "_get_log_file", lambda: None)

    eh._show_error_dialog("oops", "details")

    assert created["called"]
    assert new_root.destroyed


def test_dialog_failure_is_recorded(monkeypatch):
    """If showing the dialog fails the error should be logged and recorded."""

    eh.RECENT_ERRORS.clear()

    class BadTk:
        @property
        def _default_root(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(eh, "tk", BadTk(), raising=False)
    monkeypatch.setattr(eh, "messagebox", None, raising=False)

    eh._show_error_dialog("oops", "details")

    assert any("DialogError" in e and "boom" in e for e in eh.RECENT_ERRORS)


def test_uninstall_restores_hooks():
    eh.uninstall()  # ensure a clean slate if another test installed it
    orig_excepthook = sys.excepthook
    orig_showwarning = warnings.showwarning
    orig_unraisable = getattr(sys, "unraisablehook", None)
    orig_thread_hook = getattr(threading, "excepthook", None)

    eh.install()
    eh.uninstall()

    assert sys.excepthook is orig_excepthook
    assert warnings.showwarning is orig_showwarning
    if hasattr(sys, "unraisablehook"):
        assert sys.unraisablehook is orig_unraisable
    if hasattr(threading, "excepthook"):
        assert threading.excepthook is orig_thread_hook


def test_cli_check():
    env = os.environ.copy()
    env["COOLBOX_LIGHTWEIGHT"] = "1"
    cmd = [sys.executable, "-m", "src.app.error_handler", "--check", "--uninstall"]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert proc.returncode == 0
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert data["installed"] is True
    assert data["warnings_chained"] is True


def test_cli_trigger_error_invokes_handler():
    env = os.environ.copy()
    env["COOLBOX_LIGHTWEIGHT"] = "1"
    cmd = [sys.executable, "-m", "src.app.error_handler", "--trigger-error", "--uninstall"]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert proc.returncode == 0
    # our handler should log the simulated unhandled exception
    assert "test error from trigger_test_error" in proc.stderr
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert data["installed"] is True


def test_cli_simulate_handler_failure():
    env = os.environ.copy()
    env["COOLBOX_LIGHTWEIGHT"] = "1"
    cmd = [
        sys.executable,
        "-m",
        "src.app.error_handler",
        "--trigger-error",
        "--simulate-handler-failure",
        "--uninstall",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert proc.returncode == 0
    assert "Critical failure in error handler" in proc.stderr


def test_cli_diagnose_ui_reports_headless():
    env = os.environ.copy()
    env["COOLBOX_LIGHTWEIGHT"] = "1"
    cmd = [
        sys.executable,
        "-m",
        "src.app.error_handler",
        "--diagnose-ui",
        "--uninstall",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert proc.returncode == 0
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert data["ui"]["headless"] is True


def test_safe_handle_exception_fallback(monkeypatch, capsys):
    """``safe_handle_exception`` should report if ``handle_exception`` fails."""

    def boom(exc, value, tb):  # pragma: no cover - injected failure
        raise RuntimeError("handler exploded")

    monkeypatch.setattr(eh, "handle_exception", boom)

    eh.safe_handle_exception(RuntimeError, RuntimeError("boom"), None)

    captured = capsys.readouterr()
    assert "Critical failure" in captured.err
    assert "handler exploded" in captured.err


def test_last_resort_report_creates_file(monkeypatch):
    """Fallback reporter should write details to a temporary file when logging fails."""

    def boom(exc, value, tb):  # pragma: no cover - injected failure
        raise RuntimeError("handler exploded")

    monkeypatch.setattr(eh, "handle_exception", boom)

    def bad_error(*a, **k):  # pragma: no cover - injected failure
        raise RuntimeError("logging exploded")

    monkeypatch.setattr(eh.logger, "error", bad_error)

    # Redirect stderr so we can inspect the message
    import io, re, os

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", buf)
    monkeypatch.setattr(sys, "__stderr__", buf, raising=False)

    eh.safe_handle_exception(RuntimeError, RuntimeError("boom"), None)

    out = buf.getvalue()
    match = re.search(r"/[^\s]*error_handler_\w+\.log", out)
    assert match, out
    path = match.group(0)
    assert os.path.exists(path)
    try:
        with open(path) as fh:
            data = fh.read()
        assert "handler exploded" in data
    finally:
        os.remove(path)


def test_error_boundary_context_manager():
    """Exceptions inside ``error_boundary`` are handled and recorded."""

    eh.RECENT_ERRORS.clear()
    with eh.error_boundary():
        raise RuntimeError("boundary boom")

    assert any("boundary boom" in e for e in eh.RECENT_ERRORS)

    with pytest.raises(RuntimeError):
        with eh.error_boundary(reraise=True):
            raise RuntimeError("boom again")
