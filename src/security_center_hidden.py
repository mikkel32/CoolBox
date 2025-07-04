"""Launch the Security Center dialog without showing a console window."""
from __future__ import annotations

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from .utils.win_console import hide_terminal, spawn_detached, silence_stdio
from .app import CoolBoxApp
from .views.security_dialog import SecurityDialog


def _relaunch_if_needed() -> None:
    if os.environ.get("COOLBOX_HIDDEN") == "1":
        return
    hide_terminal(detach=False)
    os.environ["COOLBOX_HIDDEN"] = "1"
    spawn_detached([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
    sys.exit(0)


_relaunch_if_needed()
detach = os.environ.get("COOLBOX_HIDDEN") != "1"
hide_terminal(detach=detach)
silence_stdio()


def main() -> None:
    app = CoolBoxApp()
    app.window.withdraw()
    SecurityDialog(app)
    app.window.mainloop()


if __name__ == "__main__":
    main()
