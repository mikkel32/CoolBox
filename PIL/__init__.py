"""Compatibility loader for the Pillow package.

This module attempts to import the real :mod:`PIL` implementation if it is
installed.  When the library is unavailable or ``COOLBOX_FORCE_STUB`` is set to
``1``, the very small fallback stubs bundled with CoolBox are used instead.
This ensures an installed Pillow is never shadowed by the stubs.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import os
import site
import sys
from types import ModuleType


def _load_system_pillow() -> ModuleType | None:
    """Return the installed Pillow package if found."""

    if os.environ.get("COOLBOX_FORCE_STUB") == "1":
        return None

    search_paths = site.getsitepackages() + [site.getusersitepackages()]
    for path in search_paths:
        try:
            spec = importlib.machinery.PathFinder.find_spec("PIL", [path])
        except Exception:
            spec = None
        if spec and spec.origin and spec.origin != __file__:
            module = importlib.util.module_from_spec(spec)
            assert spec.loader
            # Remove this module entry before executing the real package to avoid
            # recursion when it performs relative imports.
            sys.modules.pop(__name__, None)
            sys.modules["PIL"] = module
            spec.loader.exec_module(module)
            return module
    return None


module = _load_system_pillow()
if module is None:
    from .Image import Image  # noqa: F401
    from .ImageTk import PhotoImage  # noqa: F401
    from . import ImageGrab  # noqa: F401
    from .PngImagePlugin import PngInfo  # noqa: F401

    __all__ = ["Image", "PhotoImage", "ImageGrab", "PngInfo"]
else:
    for name in getattr(module, "__all__", dir(module)):
        globals()[name] = getattr(module, name)
    __all__ = getattr(module, "__all__", [n for n in globals() if not n.startswith("_")])
