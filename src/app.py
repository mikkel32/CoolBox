"""
CoolBox Application Class
Manages the main application window and navigation
"""
try:
    import customtkinter as ctk
except ImportError:  # pragma: no cover - runtime dependency check
    from .ensure_deps import ensure_customtkinter

    ctk = ensure_customtkinter()
from typing import Dict, Optional
import sys

from .config import Config
from .components.sidebar import Sidebar
from .components.toolbar import Toolbar
from .components.status_bar import StatusBar
from .views.home_view import HomeView
from .views.tools_view import ToolsView
from .views.settings_view import SettingsView
from .views.about_view import AboutView
from .models.app_state import AppState
from .utils.theme import ThemeManager
from .utils.helpers import log


class CoolBoxApp:
    """Main application class"""

    def __init__(self):
        """Initialize the application"""
        # Load configuration
        self.config = Config()
        self.state = AppState()

        # Set appearance
        ctk.set_appearance_mode(self.config.get("appearance_mode", "dark"))
        ctk.set_default_color_theme(self.config.get("color_theme", "blue"))

        # Create main window
        self.window = ctk.CTk()
        self.window.title("CoolBox - Modern Desktop App")
        self.window.geometry(f"{self.config.get('window_width', 1200)}x{self.config.get('window_height', 800)}")

        # Set minimum window size
        self.window.minsize(800, 600)

        # Theme manager
        self.theme = ThemeManager()
        self.theme.apply_theme(self.config.get("theme", {}))
        log("Initialized theme manager")

        # Initialize views dict
        self.views: Dict[str, ctk.CTkFrame] = {}
        self.current_view: Optional[str] = None

        # Setup UI
        self._setup_ui()

        # Bind events
        self._bind_events()

        # Load initial view
        self.switch_view("home")

    def _setup_ui(self):
        """Setup the main UI layout"""
        # Create main container
        self.main_container = ctk.CTkFrame(self.window, corner_radius=0)
        self.main_container.pack(fill="both", expand=True)

        # Create toolbar if enabled in config
        self.toolbar: Toolbar | None = None
        if self.config.get("show_toolbar", True):
            self.toolbar = Toolbar(self.main_container, self)
            self.toolbar.pack(fill="x", padx=0, pady=0)

        # Create content area with sidebar
        self.content_area = ctk.CTkFrame(self.main_container, corner_radius=0)
        self.content_area.pack(fill="both", expand=True)

        # Configure grid
        self.content_area.grid_rowconfigure(0, weight=1)
        self.content_area.grid_columnconfigure(1, weight=1)

        # Create sidebar
        self.sidebar = Sidebar(self.content_area, self)
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        # Create view container
        self.view_container = ctk.CTkFrame(self.content_area, corner_radius=0)
        self.view_container.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)

        # Create status bar if enabled
        self.status_bar: StatusBar | None = None
        if self.config.get("show_statusbar", True):
            self.status_bar = StatusBar(self.main_container)
            self.status_bar.pack(fill="x", side="bottom")

        # Initialize views
        self._init_views()

    def update_ui_visibility(self) -> None:
        """Show or hide optional UI elements based on config."""
        if self.config.get("show_toolbar", True):
            if self.toolbar is None:
                self.toolbar = Toolbar(self.main_container, self)
                self.toolbar.pack(fill="x", padx=0, pady=0)
        elif self.toolbar is not None:
            self.toolbar.destroy()
            self.toolbar = None

        if self.config.get("show_statusbar", True):
            if self.status_bar is None:
                self.status_bar = StatusBar(self.main_container)
                self.status_bar.pack(fill="x", side="bottom")
        elif self.status_bar is not None:
            self.status_bar.destroy()
            self.status_bar = None

    def _init_views(self):
        """Initialize all application views"""
        self.views["home"] = HomeView(self.view_container, self)
        self.views["tools"] = ToolsView(self.view_container, self)
        self.views["settings"] = SettingsView(self.view_container, self)
        self.views["about"] = AboutView(self.view_container, self)

    def _bind_events(self):
        """Bind window events"""
        self.window.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Bind keyboard shortcuts
        self.window.bind("<Escape>", lambda e: self._on_closing())
        self.window.bind("<Control-h>", lambda e: self.switch_view("home"))
        self.window.bind("<Control-t>", lambda e: self.switch_view("tools"))
        self.window.bind("<Control-s>", lambda e: self.switch_view("settings"))
        self.window.bind("<F11>", lambda e: self.toggle_fullscreen())

    def switch_view(self, view_name: str):
        """Switch to a different view"""
        if view_name not in self.views:
            if self.status_bar is not None:
                self.status_bar.set_message(
                    f"View '{view_name}' not found", "error"
                )
            return

        # Hide current view
        if self.current_view:
            self.views[self.current_view].pack_forget()

        # Show new view
        self.views[view_name].pack(fill="both", expand=True)
        self.current_view = view_name
        self.state.current_view = view_name

        log(f"Switched view to {view_name}")

        # Update sidebar selection
        self.sidebar.set_active(view_name)

        # Update status
        if self.status_bar is not None:
            self.status_bar.set_message(
                f"Switched to {view_name.title()}", "info"
            )

    def toggle_fullscreen(self):
        """Toggle fullscreen mode"""
        current_state = self.window.attributes("-fullscreen")
        self.window.attributes("-fullscreen", not current_state)

    def _on_closing(self):
        """Handle window closing event"""
        # Save configuration
        self.config.set("window_width", self.window.winfo_width())
        self.config.set("window_height", self.window.winfo_height())
        self.config.save()

        log("Application closing")

        # Destroy window
        self.window.destroy()
        sys.exit(0)

    def run(self):
        """Start the application"""
        log("Starting main loop")
        self.window.mainloop()

    def destroy(self):
        """Destroy the application window."""
        self.window.destroy()
        log("Window destroyed")
