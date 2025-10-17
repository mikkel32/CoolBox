import json
from types import SimpleNamespace
from typing import cast

import os

os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")

from coolbox.ui.views.dialogs.force_quit import ForceQuitDialog
from coolbox.ui.views.overlays.click_overlay import OverlayState, ClickOverlay


def test_finish_kill_by_click_serializes_overlay_state(capsys):
    dialog = ForceQuitDialog.__new__(ForceQuitDialog)
    overlay = SimpleNamespace(
        state=OverlayState.INIT,
        _cursor_x=0,
        _cursor_y=0,
        pid=None,
        title_text=None,
        _last_ping=0.0,
        _watchdog_misses=0,
        reset=lambda: None,
        close=lambda: None,
        on_hover=None,
    )
    dialog._overlay = cast(ClickOverlay, overlay)
    dialog._overlay_ctx = cast(
        ForceQuitDialog._OverlayContext,
        SimpleNamespace(__exit__=lambda *args: False, __enter__=lambda: overlay),
    )
    dialog._overlay_thread = None
    dialog._overlay_watchdog_proc = None
    dialog._overlay_sync = None
    dialog._overlay_poller = None
    dialog._overlay_last_ping_file = None

    assert dialog._overlay_ctx is not None

    dialog._finish_kill_by_click(dialog._overlay_ctx, Exception("boom"))
    err = capsys.readouterr().err.strip().splitlines()
    assert err[0] == "Kill by Click raised an exception"
    info = json.loads("\n".join(err[1:]))
    assert info["state"] == "OverlayState.INIT"
