"""Standalone entry point for the Security Center dialog."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from .app import CoolBoxApp  # noqa: E402
from .views.security_dialog import SecurityDialog  # noqa: E402


def main() -> None:
    app = CoolBoxApp()
    app.window.withdraw()
    SecurityDialog(app)
    app.window.mainloop()


if __name__ == "__main__":
    main()
