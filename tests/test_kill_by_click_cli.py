import scripts.kill_by_click as kbc


def test_main_invokes_overlay(monkeypatch):
    called = {}

    class DummyOverlay:
        def __init__(self, root, *, skip_confirm=False, interval=None):
            called['skip_confirm'] = skip_confirm
            called['interval'] = interval

        def choose(self):
            called['choose'] = True
            return (123, 'title')

    monkeypatch.setattr(kbc, 'ClickOverlay', DummyOverlay)
    monkeypatch.setattr(kbc.tk, 'Tk', lambda: type('T', (), {'withdraw': lambda self: None, 'destroy': lambda self: None})())

    kbc.main(['--skip-confirm', '--interval', '0.2'])

    assert called.get('choose')
    assert called.get('skip_confirm') is True
    assert called.get('interval') == 0.2
