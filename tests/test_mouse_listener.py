from src.utils import mouse_listener


def test_global_listener_singleton(monkeypatch):
    events = {"start": 0, "stop": 0}

    class DummyListener:
        def __init__(self, on_move=None, on_click=None):
            self.on_move = on_move
            self.on_click = on_click
            self._alive = False

        def start(self):
            self._alive = True
            events["start"] += 1

        def stop(self):
            self._alive = False
            events["stop"] += 1

        def join(self):
            pass

        def is_alive(self):
            return self._alive

    class DummyMouse:
        Listener = DummyListener

    monkeypatch.setattr(mouse_listener, "mouse", DummyMouse)

    listener = mouse_listener.get_global_listener()
    assert listener is mouse_listener.get_global_listener()

    assert listener.start()
    assert events["start"] == 1

    assert listener.start()
    assert events["start"] == 1  # no new Listener started

    listener.stop()
    assert events["stop"] == 1
    listener.stop()
    assert events["stop"] == 1  # stop only once


def test_keyboard_listener(monkeypatch):
    events = {"start": 0, "stop": 0}

    class DummyKeyboardListener:
        def __init__(self, on_press=None):
            self.on_press = on_press
            self._alive = False

        def start(self):
            self._alive = True
            events["start"] += 1

        def stop(self):
            self._alive = False
            events["stop"] += 1

        def join(self):
            pass

        def is_alive(self):
            return self._alive

    class DummyKeyboard:
        Listener = DummyKeyboardListener

    monkeypatch.setattr(mouse_listener, "mouse", None)
    monkeypatch.setattr(mouse_listener, "keyboard", DummyKeyboard)

    listener = mouse_listener.GlobalMouseListener()
    assert listener.start(on_key=lambda key, pressed: None)
    assert events["start"] == 1
    listener.stop()
    assert events["stop"] == 1
