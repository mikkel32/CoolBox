import scripts.kill_by_click as kbc


def test_main_invokes_overlay(monkeypatch):
    called = {}

    class DummyOverlay:
        def __init__(self, root, **_):
            called['init'] = True

        def choose(self):
            called['choose'] = True
            return (123, 'title')

    monkeypatch.setattr(kbc, 'ClickOverlay', DummyOverlay)
    monkeypatch.setattr(kbc.tk, 'Tk', lambda: type('T', (), {'withdraw': lambda self: None, 'destroy': lambda self: None})())

    kbc.main()

    assert called.get('init')
    assert called.get('choose')
