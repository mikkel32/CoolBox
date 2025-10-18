"""Launch the Security Center dialog without the full app."""
from __future__ import annotations

import sys

from coolbox.app import CoolBoxApp  # noqa: E402
from coolbox.ui.views.dialogs.security import SecurityDialog  # noqa: E402
from coolbox.utils import security  # noqa: E402
import tkinter as tk
from typing import cast


def main() -> None:
    if not security.is_admin():
        security.relaunch_security_center(sys.argv[1:])
        return

    app = CoolBoxApp()
    app.window.withdraw()
    top = tk.Toplevel(app.window)
    SecurityDialog(cast("tk.Misc", top))
    top.protocol("WM_DELETE_WINDOW", app.window.destroy)
    app.window.mainloop()


if __name__ == "__main__":
    main()
