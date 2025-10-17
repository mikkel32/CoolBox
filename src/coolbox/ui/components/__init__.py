"""Structured collection of reusable UI components."""
from __future__ import annotations

import sys
from importlib import import_module
from types import ModuleType

try:
    from . import charts, dialogs, layout, widgets  # noqa: F401
except Exception:  # pragma: no cover - optional GUI deps
    # Some UI components require GUI libraries that might be missing in CI. We
    # expose the names so attribute access fails gracefully at runtime.
    charts = dialogs = layout = widgets = None  # type: ignore[assignment]

from .charts import BarChart, Gauge, LineChart
from .layout import MenuBar, Sidebar, StatusBar, Toolbar
from .widgets import Tooltip, info_label

try:  # pragma: no cover - optional GUI dependency
    from .dialogs import ModernErrorDialog
except Exception:  # pragma: no cover - missing runtime deps
    ModernErrorDialog = None  # type: ignore[assignment]

__all__ = [
    "charts",
    "dialogs",
    "layout",
    "widgets",
    "Sidebar",
    "Toolbar",
    "StatusBar",
    "MenuBar",
    "info_label",
    "Tooltip",
    "LineChart",
    "Gauge",
    "BarChart",
    "ModernErrorDialog",
]


def _load_legacy(name: str) -> ModuleType | None:
    """Attempt to load a module for compatibility aliases."""

    try:
        return import_module(name, __name__)
    except Exception:  # pragma: no cover - optional dependencies missing
        return None


_legacy_modules: dict[str, ModuleType] = {}
for alias, target in {
    "bar_chart": ".charts.bar_chart",
    "gauge": ".charts.gauge",
    "toolbar": ".layout.toolbar",
    "status_bar": ".layout.status_bar",
    "menubar": ".layout.menubar",
    "sidebar": ".layout.sidebar",
    "tooltip": ".widgets.tooltip",
    "modern_error_dialog": ".dialogs.modern_error_dialog",
}.items():
    module = _load_legacy(target)
    if module is not None:
        _legacy_modules[alias] = module

for alias, module in _legacy_modules.items():
    sys.modules[f"{__name__}.{alias}"] = module


del ModuleType, import_module, sys, _legacy_modules, _load_legacy
