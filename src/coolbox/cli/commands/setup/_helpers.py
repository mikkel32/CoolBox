"""Optional helper imports used by the setup command."""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

__all__ = ["ensure_numpy", "get_system_info", "helper_console"]

try:  # pragma: no cover - best effort optional dependency
    from coolbox.ensure_deps import ensure_numpy  # type: ignore
except Exception as exc:  # pragma: no cover - fallback when helper missing
    print(f"Warning: could not import ensure_numpy ({exc}).", file=sys.stderr)

    def ensure_numpy(version: str | None = None) -> ModuleType:  # type: ignore
        try:
            return __import__("numpy")
        except ImportError as np_exc:  # pragma: no cover - defensive fallback
            msg = "numpy is required but was not found. Install it with 'pip install numpy'."
            print(msg, file=sys.stderr)
            raise ImportError(msg) from np_exc

try:  # pragma: no cover - optional helper
    from coolbox.utils.system_utils import (  # type: ignore
        get_system_info,
        console as helper_console,
    )
except Exception as exc:  # pragma: no cover - fallback when helper missing
    print(f"Warning: helper utilities unavailable ({exc}). Using fallbacks.", file=sys.stderr)
    helper_console = None

    def get_system_info() -> str:  # type: ignore
        python = f"Python {sys.version.split()[0]} ({sys.executable})"
        details = [python, f"Platform: {sys.platform}", f"CWD: {Path.cwd()}"]
        return "\n".join(details)
