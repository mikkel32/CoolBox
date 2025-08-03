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


def test_hover_immediate():
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog.tree = mock.Mock()
    dialog._set_hover_row = mock.Mock()
    dialog.after = mock.Mock()
    dialog.after_cancel = mock.Mock()

    dialog.tree.identify_row.side_effect = ["row1", "row2"]

    evt1 = types.SimpleNamespace(y=5)
    evt2 = types.SimpleNamespace(y=10)
    dialog._on_hover(evt1)
    dialog._on_hover(evt2)

    assert dialog._set_hover_row.call_args_list == [mock.call("row1"), mock.call("row2")]
    dialog.after.assert_not_called()
    dialog.after_cancel.assert_not_called()
