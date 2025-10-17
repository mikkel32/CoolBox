import tkinter as tk
from types import SimpleNamespace
from typing import cast

from coolbox.ui.views.dialogs.force_quit import ForceQuitDialog


class Dummy:
    def __init__(self) -> None:
        self.state = tk.DISABLED

    def configure(self, *, state: str) -> None:
        self.state = state


def test_kill_actions_enable_once() -> None:
    dialog = SimpleNamespace(
        process_snapshot={},
        _enum_progress=0.0,
        _actions_enabled=False,
        kill_selected_btn=Dummy(),
        _action_buttons=[Dummy(), Dummy()],
    )

    ForceQuitDialog._update_kill_actions(cast(ForceQuitDialog, dialog))
    assert dialog.kill_selected_btn.state == tk.DISABLED

    dialog.process_snapshot[1] = object()
    ForceQuitDialog._update_kill_actions(cast(ForceQuitDialog, dialog))
    assert dialog.kill_selected_btn.state == tk.NORMAL

    dialog._enum_progress = 0.0
    ForceQuitDialog._update_kill_actions(cast(ForceQuitDialog, dialog))
    assert dialog.kill_selected_btn.state == tk.NORMAL

