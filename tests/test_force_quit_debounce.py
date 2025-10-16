import types
from typing import Any, Callable, cast
from unittest import mock

from src.views.force_quit_dialog import ForceQuitDialog


def test_populate_debounce() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    delays: list[int] = []
    callbacks: list[Callable[[], Any]] = []

    def fake_after(ms: int, func: Callable[..., Any], *args: Any) -> str:
        delays.append(ms)
        callbacks.append(lambda: func(*args))
        return f"id{len(callbacks)}"

    cancelled = []

    def fake_after_cancel(ident: str) -> None:
        cancelled.append(ident)

    dialog.after = cast(Any, fake_after)
    dialog.after_cancel = cast(Any, fake_after_cancel)
    dialog._apply_filter_sort = mock.Mock()
    dialog._debounce_id = None

    dialog._populate()
    dialog._populate()

    assert delays == [100, 100]
    assert cancelled == ["id1"]

    callbacks[-1]()
    dialog._apply_filter_sort.assert_called_once()


def test_hover_immediate() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog.tree = mock.Mock()
    dialog._set_hover_row = mock.Mock()
    after_mock = mock.Mock()
    after_cancel_mock = mock.Mock()
    dialog.after = cast(Any, after_mock)
    dialog.after_cancel = cast(Any, after_cancel_mock)

    dialog.tree.identify_row.side_effect = ["row1", "row2"]

    evt1 = types.SimpleNamespace(x=0, y=5, widget=dialog.tree)
    evt2 = types.SimpleNamespace(x=0, y=10, widget=dialog.tree)
    dialog._on_hover(evt1)
    dialog._on_hover(evt2)

    assert dialog._set_hover_row.call_args_list == [mock.call("row1"), mock.call("row2")]
    after_mock.assert_not_called()
    after_cancel_mock.assert_not_called()


def test_update_hover_no_global_pointer_calls() -> None:
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    dialog.tree = mock.Mock()
    dialog._set_hover_row = mock.Mock()
    dialog.winfo_pointerxy = mock.Mock(side_effect=AssertionError("should not be called"))
    dialog.winfo_containing = mock.Mock(side_effect=AssertionError("should not be called"))

    dialog.tree.identify_row.return_value = "row"

    evt = types.SimpleNamespace(x=0, y=5, widget=dialog.tree)
    dialog._on_hover(evt)
    dialog._update_hover()

    dialog.winfo_pointerxy.assert_not_called()
    dialog.winfo_containing.assert_not_called()
    dialog._set_hover_row.assert_called_with("row")
