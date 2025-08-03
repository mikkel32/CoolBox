import scripts.kill_by_click as kbc


def test_main_invokes_overlay(monkeypatch):
    called = {}

    class DummyOverlay:
        def __init__(
            self,
            root,
            *,
            skip_confirm=False,
            interval=None,
            min_interval=None,
            max_interval=None,
            delay_scale=None,
        ):
            called['skip_confirm'] = skip_confirm
            called['interval'] = interval
            called['min_interval'] = min_interval
            called['max_interval'] = max_interval
            called['delay_scale'] = delay_scale

        def choose(self):
            called['choose'] = True
            return (123, 'title')

    monkeypatch.setattr(kbc, 'ClickOverlay', DummyOverlay)
    monkeypatch.setattr(kbc.tk, 'Tk', lambda: type('T', (), {'withdraw': lambda self: None, 'destroy': lambda self: None})())

    kbc.main([
        '--skip-confirm',
        '--interval', '0.2',
        '--min-interval', '0.05',
        '--max-interval', '0.3',
        '--delay-scale', '500',
    ])

    assert called.get('choose')
    assert called.get('skip_confirm') is True
    assert called.get('interval') == 0.2
    assert called.get('min_interval') == 0.05
    assert called.get('max_interval') == 0.3
    assert called.get('delay_scale') == 500.0


def test_calibrate_flag(monkeypatch, capsys):
    class DummyOverlay:
        @staticmethod
        def auto_tune_interval():
            return (0.1, 0.05, 0.2)

        def __init__(self, *a, **kw):
            raise AssertionError("Overlay should not be constructed")

    monkeypatch.setattr(kbc, 'ClickOverlay', DummyOverlay)
    kbc.main(['--calibrate'])
    out = capsys.readouterr().out
    assert 'Calibrated' in out
