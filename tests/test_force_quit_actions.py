import tkinter as tk
from types import SimpleNamespace

from src.views.force_quit_dialog import ForceQuitDialog


class Dummy:
    def __init__(self) -> None:
        self.state = tk.DISABLED

    def configure(self, *, state: str) -> None:
        self.state = state


def test_kill_actions_enable_once() -> None:
    dialog = SimpleNamespace(
        _enum_progress=0.0,
        _actions_enabled=False,
        kill_selected_btn=Dummy(),
        _action_buttons=[Dummy(), Dummy()],
    )

    ForceQuitDialog._update_kill_actions(dialog)
    assert dialog.kill_selected_btn.state == tk.DISABLED

    dialog._enum_progress = 1.0
    ForceQuitDialog._update_kill_actions(dialog)
    assert dialog.kill_selected_btn.state == tk.NORMAL

    dialog._enum_progress = 0.0
    ForceQuitDialog._update_kill_actions(dialog)
    assert dialog.kill_selected_btn.state == tk.NORMAL

