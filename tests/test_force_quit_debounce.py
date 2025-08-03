import types
from unittest import mock

import types
from unittest import mock

from src.views.force_quit_dialog import ForceQuitDialog


def test_populate_debounce():
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    delays: list[int] = []
    callbacks = []

    def fake_after(delay: int, func):
        delays.append(delay)
        callbacks.append(func)
        return f"id{len(callbacks)}"

    cancelled = []

    def fake_after_cancel(ident: str) -> None:
        cancelled.append(ident)

    dialog.after = fake_after
    dialog.after_cancel = fake_after_cancel
    dialog._apply_filter_sort = mock.Mock()
    dialog._debounce_id = None

    dialog._populate()
    dialog._populate()

    assert delays == [100, 100]
    assert cancelled == ["id1"]

    callbacks[-1]()
    dialog._apply_filter_sort.assert_called_once()


def test_hover_debounce():
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    callbacks = []

    def fake_after(delay: int, func):
        callbacks.append((delay, func))
        return f"id{len(callbacks)}"

    cancelled = []

    def fake_after_cancel(ident: str) -> None:
        cancelled.append(ident)

    dialog.after = fake_after
    dialog.after_cancel = fake_after_cancel
    dialog._update_hover = mock.Mock()
    dialog._hover_after_id = None

    evt = types.SimpleNamespace(y=5)
    dialog._on_hover(evt)
    dialog._on_hover(evt)

    assert [d for d, _ in callbacks] == [100, 100]
    assert cancelled == ["id1"]

    callbacks[-1][1]()
    dialog._update_hover.assert_called_once()
