"""Lightweight shim for the Rich library.

If the actual :mod:`rich` package is installed it will be used in preference to
this built-in fallback implementation. Only a very small subset of the Rich API
is provided when falling back.
"""

from __future__ import annotations

import importlib

try:  # Try to use the real library if available
    _rich = importlib.import_module("rich")
    if _rich.__file__ != __file__:
        globals().update(_rich.__dict__)
    else:  # pragma: no cover - shouldn't happen but guards against recursion
        raise ImportError
except Exception:  # pragma: no cover - fallback
    from .console import Console, Control, Group
    from .progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, BarColumn
    from .text import Text
    from .table import Table
    from .live import Live

    __all__ = [
        "Console",
        "Control",
        "Group",
        "Progress",
        "SpinnerColumn",
        "TextColumn",
        "TimeElapsedColumn",
        "BarColumn",
        "Table",
        "Live",
        "Text",
    ]
