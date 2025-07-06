import builtins
import importlib
import sys
import types

import main

class DummyDisplay:
    def __init__(self, *, visible, size):
        assert visible is False
        assert size == (1024, 768)
        self.started = False
        self.stopped = False
    def start(self):
        self.started = True
    def stop(self):
        self.stopped = True

def test_main_starts_virtual_display(monkeypatch):
    display = DummyDisplay(visible=False, size=(1024, 768))
    dummy_module = types.SimpleNamespace(Display=lambda **kw: display)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setitem(sys.modules, "pyvirtualdisplay", dummy_module)
    monkeypatch.setattr(main, "_run_setup_if_needed", lambda: None)
    called = {}
    class DummyApp:
        def __init__(self):
            called["init"] = True
        def run(self):
            called["run"] = True
    monkeypatch.setattr(main, "CoolBoxApp", DummyApp)
    monkeypatch.setattr(sys, "argv", ["main.py"])
    main.main()
    assert called == {"init": True, "run": True}
    assert display.started
    assert display.stopped
