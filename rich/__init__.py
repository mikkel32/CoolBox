"""Thin wrapper around the real Rich package that patches ProgressColumn.
This wrapper loads the genuine package from site-packages and exposes all of
its public attributes while ensuring ``ProgressColumn`` defines
``_table_column``.  This prevents attribute errors when a subclass forgets to
initialize the base class (as seen with ``RainbowSpinnerColumn`` during setup).
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

_this_dir = Path(__file__).resolve().parent
search_paths = [p for p in sys.path[1:] if Path(p) != _this_dir.parent]
_spec = importlib.machinery.PathFinder.find_spec("rich", search_paths)
_real = importlib.util.module_from_spec(_spec)
# Insert into sys.modules before executing so relative imports work
sys.modules[__name__] = _real
_spec.loader.exec_module(_real)  # type: ignore[attr-defined]

# Patch ProgressColumn once the real module is ready
try:  # pragma: no cover - defensive
    from rich.progress import ProgressColumn  # type: ignore
    if not hasattr(ProgressColumn, "_table_column"):
        ProgressColumn._table_column = None
except Exception:
    pass

# Re-export everything from the real module
globals().update(_real.__dict__)
