#!/usr/bin/env python3
"""Launch the Security Center dialog without showing a console window."""
from __future__ import annotations

import sys
import os
import subprocess
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.win_console import (  # noqa: E402
    hide_terminal,
    hidden_creation_flags,
    silence_stdio,
)
from src.app import CoolBoxApp  # noqa: E402
from src.views.security_dialog import SecurityDialog  # noqa: E402


# Hide the terminal ASAP before creating any Tk windows.
def _relaunch_if_needed() -> None:
    """Relaunch detached so no console window remains visible."""
    if os.environ.get("COOLBOX_HIDDEN") == "1":
        return

    exe = Path(sys.executable)

    if platform.system() == "Windows":
        if exe.name.lower() == "python.exe":
            pythonw = exe.with_name("pythonw.exe")
            if pythonw.is_file():
                exe = pythonw
        flags = hidden_creation_flags()
        os.environ["COOLBOX_HIDDEN"] = "1"
        subprocess.Popen(
            [str(exe), str(Path(__file__).resolve()), *sys.argv[1:]],
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        sys.exit(0)

    # POSIX: spawn a detached copy in a new session
    os.environ["COOLBOX_HIDDEN"] = "1"
    subprocess.Popen(
        [str(exe), str(Path(__file__).resolve()), *sys.argv[1:]],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
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
