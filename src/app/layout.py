from __future__ import annotations

try:
    import customtkinter as ctk
except ImportError:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_customtkinter

    ctk = ensure_customtkinter()

from ..components.sidebar import Sidebar
from ..components.toolbar import Toolbar
from ..components.status_bar import StatusBar
from ..components.menubar import MenuBar
from ..views.home_view import HomeView
from ..views.tools_view import ToolsView
from ..views.settings_view import SettingsView
from ..views.about_view import AboutView
from ..utils.system_utils import log


def setup_ui(app) -> None:
    """Configure the main user interface for *app*.

    Raises:
        RuntimeError: If any part of the layout initialization fails.
    """
    try:
        app.main_container = ctk.CTkFrame(app.window, corner_radius=0)
        app.main_container.pack(fill="both", expand=True)

        app.menu_bar = None
        if app.config.get("show_menu", True):
            app.menu_bar = MenuBar(app.window, app)

        app.toolbar = None
        if app.config.get("show_toolbar", True):
            app.toolbar = Toolbar(app.main_container, app)
            app.toolbar.pack(fill="x", padx=0, pady=0)

        app.content_area = ctk.CTkFrame(app.main_container, corner_radius=0)
        app.content_area.pack(fill="both", expand=True)

        app.content_area.grid_rowconfigure(0, weight=1)
        app.content_area.grid_columnconfigure(1, weight=1)

        app.sidebar = Sidebar(app.content_area, app)
        app.sidebar.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        app.view_container = ctk.CTkFrame(app.content_area, corner_radius=0)
        app.view_container.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)

        app.status_bar = None
        if app.config.get("show_statusbar", True):
            app.status_bar = StatusBar(app.main_container, app)
            app.status_bar.pack(fill="x", side="bottom")

        app.views = {
            "home": HomeView(app.view_container, app),
            "tools": ToolsView(app.view_container, app),
            "settings": SettingsView(app.view_container, app),
            "about": AboutView(app.view_container, app),
        }
        app.refresh_recent_files()
        if app.menu_bar is not None:
            app.menu_bar.refresh_toggles()
        app.update_fonts()
        app.update_theme()
    except Exception as exc:
        log(f"Failed to set up UI: {exc}")
        raise RuntimeError(f"Failed to set up UI: {exc}") from exc
