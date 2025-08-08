import types

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
    assert events["stop"] == 0
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


def test_wrap_callbacks_log_exceptions(monkeypatch):
    messages = []
    monkeypatch.setattr(
        mouse_listener,
        "logger",
        types.SimpleNamespace(exception=lambda msg, *a, **k: messages.append(msg)),
    )
    listener = mouse_listener.GlobalMouseListener()

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    move_cb = listener._wrap_move(boom)
    assert move_cb is not None
    move_cb(0, 0)

    class DummyMouse:
        class Button:
            left = 1

    monkeypatch.setattr(mouse_listener, "mouse", DummyMouse)
    click_cb = listener._wrap_click(boom)
    assert click_cb is not None
    click_cb(0, 0, DummyMouse.Button.left, True)

    key_cb = listener._wrap_key(boom)
    assert key_cb is not None
    key_cb(object())

    assert len(messages) == 3


def test_stop_logs_when_join_times_out(monkeypatch):
    messages = []
    monkeypatch.setattr(mouse_listener, "log", lambda msg: messages.append(msg))

    class StuckListener:
        def __init__(self, *args, **kwargs):
            self.join_timeout = None

        def start(self):
            pass

        def stop(self):
            pass

        def join(self, timeout=None):
            self.join_timeout = timeout

        def is_alive(self):
            return True

    class DummyMouse:
        Listener = StuckListener

    class DummyKeyboard:
        Listener = StuckListener

    monkeypatch.setattr(mouse_listener, "mouse", DummyMouse)
    monkeypatch.setattr(mouse_listener, "keyboard", DummyKeyboard)

    listener = mouse_listener.GlobalMouseListener()
    assert listener.start(on_move=lambda x, y: None, on_key=lambda k, p: None)
    mouse_inst = listener._mouse_listener
    keyboard_inst = listener._keyboard_listener
    listener.stop(force=True)

    assert mouse_inst.join_timeout is not None
    assert keyboard_inst.join_timeout is not None
    assert any("mouse listener" in m and "failed" in m for m in messages)
    assert any("keyboard listener" in m and "failed" in m for m in messages)
