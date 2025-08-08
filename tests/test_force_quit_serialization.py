import json
from types import SimpleNamespace

import os

os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")

from src.views.force_quit_dialog import ForceQuitDialog
from src.views.click_overlay import OverlayState


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
    )
    dialog._overlay = overlay
    dialog._overlay_ctx = SimpleNamespace(__exit__=lambda *args: None)
    dialog._overlay_thread = None
    dialog._overlay_watchdog_proc = None
    dialog._overlay_sync = None
    dialog._overlay_poller = None
    dialog._overlay_last_ping_file = None

    dialog._finish_kill_by_click(dialog._overlay_ctx, Exception("boom"))
    err = capsys.readouterr().err.strip().splitlines()
    assert err[0] == "Kill by Click raised an exception"
    info = json.loads("\n".join(err[1:]))
    assert info["state"] == "OverlayState.INIT"
