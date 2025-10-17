"""Compatibility shim that loads the actual CoolBox package from ``src``."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent
_src_pkg = _pkg_dir.parent / "src" / "coolbox"
if not _src_pkg.exists():
    raise ImportError(f"CoolBox package not found at {_src_pkg}")

__path__ = [str(_src_pkg)]
_spec = importlib.util.spec_from_file_location(
    __name__,
    _src_pkg / "__init__.py",
    submodule_search_locations=[str(_src_pkg)],
)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Unable to load CoolBox package from {_src_pkg}")
_spec.loader.exec_module(sys.modules[__name__])
