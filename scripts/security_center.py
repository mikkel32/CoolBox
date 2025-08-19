#!/usr/bin/env python3
"""Launch the Security Center dialog without the full app."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.app import CoolBoxApp  # noqa: E402
from src.views.security_dialog import SecurityDialog  # noqa: E402
from src.utils import security  # noqa: E402


def main() -> None:
    if not security.is_admin():
        security.relaunch_security_center()
        return

    app = CoolBoxApp()
    app.window.withdraw()
    # Pass the underlying Tk window to SecurityDialog
    SecurityDialog(app.window)
    app.window.mainloop()


if __name__ == "__main__":
    main()
