"""Expose component classes for easy import."""

from .sidebar import Sidebar
from .toolbar import Toolbar
from .status_bar import StatusBar
from .menubar import MenuBar
from .widgets import info_label
from .tooltip import Tooltip
from .charts import LineChart
from .gauge import Gauge
from .bar_chart import BarChart
try:  # pragma: no cover - optional component
    from .modern_error_dialog import ModernErrorDialog
except Exception:  # pragma: no cover - missing GUI deps
    ModernErrorDialog = None  # type: ignore

__all__ = [
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
