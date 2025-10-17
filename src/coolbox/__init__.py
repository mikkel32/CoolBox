"""Public package interface for CoolBox."""

__version__ = "1.3.76"

import os
from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING

# NumPy 2.0 deprecates ``row_stack`` and emits a warning each time it is
# used.  Matplotlib still calls this alias internally, so we replace it with
# ``vstack`` to silence the warning without altering behaviour.
try:  # pragma: no cover - optional dependency
    import numpy as _np

    if hasattr(_np, "row_stack"):
        _np.row_stack = _np.vstack  # type: ignore[attr-defined]
except Exception:
    pass

if TYPE_CHECKING:  # pragma: no cover - import real symbols for type checking
    from .app import CoolBoxApp
    from .ensure_deps import ensure_customtkinter
elif not os.environ.get("COOLBOX_LIGHTWEIGHT"):
    _LAZY_ATTRS = {
        "CoolBoxApp": ("coolbox.app", "CoolBoxApp"),
        "ensure_customtkinter": ("coolbox.ensure_deps", "ensure_customtkinter"),
    }
else:  # pragma: no cover - lightweight testing stubs

    class CoolBoxApp:
        """Minimal stub used when UI dependencies are unavailable."""

        def run(self) -> None:
            """No-op run method used for lightweight testing."""

    def ensure_customtkinter(version: str = "5.2.2") -> ModuleType:
        """Placeholder that raises when the real dependency is missing."""

        raise RuntimeError("customtkinter is unavailable in lightweight mode")

    _LAZY_ATTRS = {}


def __getattr__(name: str):
    try:
        module_name, attr = _LAZY_ATTRS[name]
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise AttributeError(name) from exc
    module = import_module(module_name)
    value = getattr(module, attr)
    globals()[name] = value
    return value


__all__ = ["CoolBoxApp", "ensure_customtkinter"]
