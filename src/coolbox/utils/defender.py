"""Compatibility wrapper for :mod:`coolbox.utils.security.defender`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from typing import TYPE_CHECKING

from .security.defender import *  # type: ignore F401,F403
from .security import defender as _defender_module

if TYPE_CHECKING:
    from .security.defender import _ps as _ps
    from .security.defender import _run_ex as _run_ex

try:  # pragma: no cover - target may not define __all__
    from .security.defender import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    _exported = [name for name in vars(_defender_module) if not name.startswith("_")]
else:
    _exported = list(__all__)
for _compat_name in ("_run_ex", "_ps"):
    if hasattr(_defender_module, _compat_name):
        globals()[_compat_name] = getattr(_defender_module, _compat_name)
        _exported.append(_compat_name)

__all__ = tuple(dict.fromkeys(_exported))

del _defender_module, _exported
