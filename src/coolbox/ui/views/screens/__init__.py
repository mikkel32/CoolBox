"""Primary application screens displayed in the main window."""
from __future__ import annotations

from .about import AboutView
from .home import HomeView
from .settings import SettingsView
from .tools import ToolsView

__all__ = [
    "AboutView",
    "HomeView",
    "SettingsView",
    "ToolsView",
]
