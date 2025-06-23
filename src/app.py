"""Main application class for CoolBox."""

import tkinter as tk
from typing import Dict, Type

from .config import Config
from .models.app_state import AppState
from .views.home_view import HomeView
from .views.tools_view import ToolsView
from .views.settings_view import SettingsView
from .views.about_view import AboutView
from .components.sidebar import Sidebar
from .components.toolbar import Toolbar
from .components.status_bar import StatusBar


class CoolBoxApp(tk.Tk):
    """Tkinter-based application window."""

    def __init__(self, config: Config | None = None) -> None:
        super().__init__()
        self.config_data = config or Config()
        self.title(self.config_data.title)
        self.geometry(self.config_data.geometry)

        self.state = AppState()

        # Layout frames
        self.toolbar = Toolbar(self)
        self.toolbar.pack(fill=tk.X)

        self.sidebar = Sidebar(self, self.on_navigate)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)

        self.container = tk.Frame(self)
        self.container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.status_bar = StatusBar(self)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.views: Dict[str, tk.Frame] = {}
        self._init_views()
        self.show_view("home")

    def _init_views(self) -> None:
        """Initialize and cache view frames."""
        self.views = {
            "home": HomeView(self.container, self),
            "tools": ToolsView(self.container, self),
            "settings": SettingsView(self.container, self),
            "about": AboutView(self.container, self),
        }
        for view in self.views.values():
            view.place(relwidth=1, relheight=1)

    def show_view(self, name: str) -> None:
        """Display the requested view."""
        if name not in self.views:
            raise ValueError(f"Unknown view: {name}")
        for view_name, view in self.views.items():
            view.tkraise() if view_name == name else None
        self.state.current_view = name
        self.status_bar.set_status(f"Viewing {name.title()}")

    def on_navigate(self, name: str) -> None:
        """Callback from sidebar when a navigation item is clicked."""
        self.show_view(name)
