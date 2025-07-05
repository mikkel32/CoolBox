import types
import sys
from src.utils.icons import set_window_icon, logo_paths


class DummyWindow:
    def __init__(self):
        self.iconphoto_calls = []
        self.iconbitmap_calls = []

    def iconphoto(self, *args):
        self.iconphoto_calls.append(args)

    def iconbitmap(self, path):
        self.iconbitmap_calls.append(path)


def test_set_window_icon_callback(monkeypatch, tmp_path):
    png = tmp_path / "logo.png"
    ico = tmp_path / "logo.ico"
    png.write_text("x")
    ico.write_text("y")
    monkeypatch.setenv("COOLBOX_LOGO_PNG", str(png))
    monkeypatch.setenv("COOLBOX_LOGO_ICO", str(ico))

    events = []
    def cb(event, detail):
        events.append(event)

    dummy_tk = types.SimpleNamespace(PhotoImage=lambda file=None: object())
    monkeypatch.setitem(sys.modules, "tkinter", dummy_tk)
    monkeypatch.setattr("src.utils.icons.Image", None)
    monkeypatch.setattr("src.utils.icons.ImageTk", None)
    monkeypatch.setattr("src.utils.icons.ctk", None)

    win = DummyWindow()
    set_window_icon(win, callback=cb)
    assert "iconphoto" in events
    assert win.iconphoto_calls

