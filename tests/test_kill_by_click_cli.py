import os
import sys
import types
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import pytest

os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")
psutil_stub = cast(Any, types.ModuleType("psutil"))
psutil_stub.net_if_addrs = lambda: {}
psutil_stub.Process = object  # type: ignore[assignment]
psutil_stub.pid_exists = lambda pid: True
sys.modules.setdefault("psutil", psutil_stub)
sys.modules.setdefault("PIL", mock.Mock())
sys.modules.setdefault("PIL.Image", mock.Mock())
sys.modules.setdefault("PIL.ImageTk", mock.Mock())
sys.modules.setdefault("pyperclip", mock.Mock())
sys.modules.setdefault("matplotlib", mock.Mock())
sys.modules.setdefault("matplotlib.pyplot", mock.Mock())
sys.modules.setdefault("matplotlib.backends", mock.Mock())
sys.modules.setdefault("matplotlib.backends.backend_tkagg", mock.Mock())
sys.modules.setdefault("matplotlib.figure", mock.Mock())

from coolbox.cli.commands import kill_by_click as kbc


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
    monkeypatch.setattr(
        kbc.tk,
        'Tk',
        lambda: cast(
            Any,
            type(
                'T',
                (),
                {'withdraw': lambda self: None, 'destroy': lambda self: None},
            )(),
        ),
    )

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


def test_main_no_display(monkeypatch, capsys):
    def raise_err():
        raise kbc.tk.TclError('no display')

    monkeypatch.setattr(kbc.tk, 'Tk', raise_err)
    with pytest.raises(SystemExit) as e:
        kbc.main([])
    assert e.value.code != 0
    assert 'No display available' in capsys.readouterr().out


def test_negative_interval_errors(capsys):
    with pytest.raises(SystemExit):
        kbc.main(['--interval', '-1'])
    assert 'interval must be positive' in capsys.readouterr().err


def test_interval_bounds(capsys):
    with pytest.raises(SystemExit):
        kbc.main(['--interval', '0.2', '--min-interval', '0.3'])
    assert 'interval must be at least min-interval' in capsys.readouterr().err

    with pytest.raises(SystemExit):
        kbc.main(['--interval', '0.5', '--max-interval', '0.4'])
    assert 'interval must be at most max-interval' in capsys.readouterr().err


def test_root_destroyed_on_exception(monkeypatch):
    destroyed = {}

    class DummyRoot:
        def withdraw(self):
            pass

        def destroy(self):
            destroyed['called'] = True

    class DummyOverlay:
        def __init__(self, *a, **kw):
            pass

        def choose(self):
            raise RuntimeError('boom')

    monkeypatch.setattr(kbc.tk, 'Tk', DummyRoot)
    monkeypatch.setattr(kbc, 'ClickOverlay', DummyOverlay)

    with pytest.raises(RuntimeError):
        kbc.main([])
    assert destroyed.get('called')
