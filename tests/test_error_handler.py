import os
import sys
import threading
import warnings
from types import SimpleNamespace

import pytest

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

