"""Compatibility wrapper for :mod:`coolbox.utils.analysis._score_samples`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

import importlib
from types import ModuleType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .analysis import _score_samples as _score_samples_module

try:  # pragma: no cover - optional extension may be missing
    _score_samples_module = importlib.import_module(
        "coolbox.utils.analysis._score_samples"
    )
except Exception:  # pragma: no cover - extension unavailable
    __all__: tuple[str, ...] = ()
else:
    module = cast(ModuleType, _score_samples_module)
    exports = getattr(module, "__all__", None)
    if exports is None:
        names = tuple(name for name in vars(module) if not name.startswith("_"))
    else:
        names = tuple(exports)
    globals().update({name: getattr(module, name) for name in names})
    __all__ = names
    del _score_samples_module
