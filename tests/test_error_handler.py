import os
import sys
import threading
import warnings
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


def test_modern_dialog_failure_is_logged(monkeypatch):
    """Failures in the modern dialog should be logged and recorded."""

    eh.RECENT_ERRORS.clear()

    class DummyRoot:
        def withdraw(self):
            pass

    monkeypatch.setattr(eh, "_get_log_file", lambda: None)

    ctk_mod = SimpleNamespace(CTk=lambda: DummyRoot())
    monkeypatch.setitem(sys.modules, "customtkinter", ctk_mod)

    class FailingDialog:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom")

    mod = SimpleNamespace(ModernErrorDialog=FailingDialog)
    monkeypatch.setitem(sys.modules, "src.components.modern_error_dialog", mod)

    class BadTk(SimpleNamespace):
        def Tk(self):
            raise RuntimeError("bad tk")

    monkeypatch.setattr(eh, "tk", BadTk(_default_root=None), raising=False)
    monkeypatch.setattr(eh, "messagebox", None, raising=False)

    eh._show_error_dialog("oops", "details")

    assert any(
        "ModernErrorDialog" in e and "boom" in e for e in eh.RECENT_ERRORS
    )


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
