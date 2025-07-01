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
            background=None,
            workers=None,
        ):
            called['skip_confirm'] = skip_confirm
            called['interval'] = interval
            called['min_interval'] = min_interval
            called['max_interval'] = max_interval
            called['delay_scale'] = delay_scale
            called['background'] = background
            called['workers'] = workers

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
        '--workers', '3',
        '--no-background',
    ])

    assert called.get('choose')
    assert called.get('skip_confirm') is True
    assert called.get('interval') == 0.2
    assert called.get('min_interval') == 0.05
    assert called.get('max_interval') == 0.3
    assert called.get('delay_scale') == 500.0
    assert called.get('background') is False
    assert called.get('workers') == 3


def test_main_background_flag(monkeypatch):
    called = {}

    class DummyOverlay:
        def __init__(self, root, *, background=None, **_kwargs):
            called['background'] = background

        def choose(self):
            called['choose'] = True
            return (None, None)

    monkeypatch.setattr(kbc, 'ClickOverlay', DummyOverlay)
    monkeypatch.setattr(kbc.tk, 'Tk', lambda: type('T', (), {'withdraw': lambda self: None, 'destroy': lambda self: None})())

    kbc.main(['--background'])

    assert called.get('choose')
    assert called.get('background') is True


def test_main_workers_flag(monkeypatch):
    called = {}

    class DummyOverlay:
        def __init__(self, root, *, workers=None, **_kwargs):
            called['workers'] = workers

        def choose(self):
            called['choose'] = True
            return (None, None)

    monkeypatch.setattr(kbc, 'ClickOverlay', DummyOverlay)
    monkeypatch.setattr(kbc.tk, 'Tk', lambda: type('T', (), {'withdraw': lambda self: None, 'destroy': lambda self: None})())

    kbc.main(['--workers', '4'])

    assert called.get('choose')
    assert called.get('workers') == 4


def test_main_cache_flag(monkeypatch):
    called = {}

    class DummyOverlay:
        def __init__(self, root, *, cache=None, **_kwargs):
            called['cache'] = cache

        def choose(self):
            called['choose'] = True
            return (None, None)

    monkeypatch.setattr(kbc, 'ClickOverlay', DummyOverlay)
    monkeypatch.setattr(kbc.tk, 'Tk', lambda: type('T', (), {'withdraw': lambda self: None, 'destroy': lambda self: None})())

    kbc.main(['--cache'])

    assert called.get('choose')
    assert called.get('cache') is True


def test_main_cache_timeout(monkeypatch):
    called = {}

    class DummyOverlay:
        def __init__(self, root, *, cache_timeout=None, **_kwargs):
            called['cache_timeout'] = cache_timeout

        def choose(self):
            called['choose'] = True
            return (None, None)

    monkeypatch.setattr(kbc, 'ClickOverlay', DummyOverlay)
    monkeypatch.setattr(kbc.tk, 'Tk', lambda: type('T', (), {'withdraw': lambda self: None, 'destroy': lambda self: None})())

    kbc.main(['--cache-timeout', '0.2'])

    assert called.get('choose')
    assert called.get('cache_timeout') == 0.2
