import types
import sys

from coolbox.app import CoolBoxApp


def test_open_force_quit_handles_errors(monkeypatch):
    class DummyApp:
        def __init__(self):
            self.force_quit_window = None

    app = DummyApp()

    # Stub messagebox.showerror to avoid GUI dependency
    errors = {}

    def fake_showerror(title, message):
        errors["title"] = title
        errors["message"] = message

    monkeypatch.setattr(
        "coolbox.app.messagebox", types.SimpleNamespace(showerror=fake_showerror), raising=False
    )

    class BoomDialog:
        def __init__(self, _app):
            raise RuntimeError("boom")

    monkeypatch.setitem(
        sys.modules,
        "coolbox.ui.views.dialogs.force_quit",
        types.SimpleNamespace(ForceQuitDialog=BoomDialog),
    )

    CoolBoxApp.open_force_quit(app)  # type: ignore[arg-type]

    assert app.force_quit_window is None
    assert errors["title"] == "Force Quit"
    assert "boom" in errors["message"]
