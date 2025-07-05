"""Load the real :mod:`customtkinter` package when available.

The project bundles a very small stub in :mod:`src.customtkinter` so the test
suite can run in environments without Tk support.  Unfortunately the presence
of this top level ``customtkinter.py`` shadowed an installed version of the
library, causing the application UI to fall back to the minimal stub even when
the real dependency was present.  To fix this we now attempt to locate and load
the system package first.  If it cannot be imported (for example on CI or when
not installed) we fall back to the bundled stub.

Set ``COOLBOX_FORCE_STUB=1`` to skip the lookup and always use the fallback.
"""

from __future__ import annotations

from types import ModuleType
import importlib
import importlib.machinery
import importlib.util
import os
import site
import sys


def _load_system_ctk() -> ModuleType | None:
    """Return the installed ``customtkinter`` module if found."""

    if os.environ.get("COOLBOX_FORCE_STUB") == "1":
        return None

    search_paths = site.getsitepackages() + [site.getusersitepackages()]
    for path in search_paths:
        try:
            spec = importlib.machinery.PathFinder.find_spec("customtkinter", [path])
        except Exception:
            spec = None
        if spec and spec.origin and spec.origin != __file__:
            module = importlib.util.module_from_spec(spec)
            assert spec.loader
            # Replace this temporary module entry before executing to avoid
            # recursion when the package performs relative imports.
            sys.modules.pop(__name__, None)
            sys.modules['customtkinter'] = module
            spec.loader.exec_module(module)
            return module
    return None


module = _load_system_ctk()
if module is None:
    module = importlib.import_module("src.customtkinter")

for name in getattr(module, "__all__", dir(module)):
    globals()[name] = getattr(module, name)

__all__ = getattr(module, "__all__", [n for n in globals() if not n.startswith("_")])
