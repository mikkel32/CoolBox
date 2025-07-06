from src.views.base_mixin import UIHelperMixin
from src.app import CoolBoxApp


class DummyWindow:
    def __init__(self, master=None):
        self.master = master
        self.titled = None
        self.sized = None

    def title(self, text):
        self.titled = text

    def geometry(self, geo):
        self.sized = geo


class DummyApp:
    def __init__(self):
        self.applied = None

    def apply_icon(self, window):
        self.applied = window



def test_create_toplevel_applies_icon(monkeypatch):
    dummy_win = DummyWindow()
    app = DummyApp()
    mixin = UIHelperMixin.__new__(UIHelperMixin)
    mixin.app = app

    def fake_create_toplevel(*, title="", geometry=None, parent=None):
        assert parent is mixin
        if title:
            dummy_win.title(title)
        if geometry:
            dummy_win.geometry(geometry)
        app.apply_icon(dummy_win)
        return dummy_win

    app.create_toplevel = fake_create_toplevel

    win = UIHelperMixin.create_toplevel(mixin, title="Foo", geometry="100x50")
    assert win is dummy_win
    assert dummy_win.titled == "Foo"
    assert dummy_win.sized == "100x50"
    assert app.applied is dummy_win


def test_app_create_toplevel_defaults_to_main(monkeypatch):
    dummy_win = DummyWindow()

    def fake_toplevel(master):
        assert master is main_window
        return dummy_win

    monkeypatch.setattr("src.app.ctk.CTkToplevel", fake_toplevel)
    app = CoolBoxApp.__new__(CoolBoxApp)
    app.window = main_window = object()
    app.applied = None

    def apply_icon(window):
        app.applied = window

    app.apply_icon = apply_icon
    win = CoolBoxApp.create_toplevel(app, title="Bar", geometry="200x100")
    assert win is dummy_win
    assert dummy_win.titled == "Bar"
    assert dummy_win.sized == "200x100"
    assert app.applied is dummy_win

