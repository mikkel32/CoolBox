"""Launch the Security Center dialog without showing a console window."""
from __future__ import annotations

import os
import sys

from coolbox.utils.win_console import (  # noqa: E402
    hide_terminal,
    spawn_detached,
    silence_stdio,
)
from coolbox.app import CoolBoxApp  # noqa: E402
from coolbox.ui.views.security_dialog import SecurityDialog  # noqa: E402
from coolbox.utils import security  # noqa: E402
import tkinter as tk
from typing import cast

if not security.is_admin():
    security.relaunch_security_center(sys.argv[1:])
    sys.exit(0)


# Hide the terminal ASAP before creating any Tk windows.
def _relaunch_if_needed() -> None:
    """Relaunch detached so no console window remains visible."""
    if os.environ.get("COOLBOX_HIDDEN") == "1":
        return

    # Hide any visible terminal window before respawning
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
    top = tk.Toplevel(app.window)
    SecurityDialog(cast("tk.Misc", top))
    top.protocol("WM_DELETE_WINDOW", app.window.destroy)
    app.window.mainloop()


if __name__ == "__main__":
    main()
