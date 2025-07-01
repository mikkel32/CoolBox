"""
CoolBox Application Class
Manages the main application window and navigation
"""
from __future__ import annotations
try:
    import customtkinter as ctk
except ImportError:  # pragma: no cover - runtime dependency check
    from .ensure_deps import ensure_customtkinter

    ctk = ensure_customtkinter()
from typing import Dict, Optional, TYPE_CHECKING
from pathlib import Path
from PIL import Image, ImageTk
import sys
import tempfile
import ctypes

from .config import Config
from .components.sidebar import Sidebar
from .components.toolbar import Toolbar
from .components.status_bar import StatusBar
from .components.menubar import MenuBar
from .views.home_view import HomeView
from .views.tools_view import ToolsView
from .views.settings_view import SettingsView
from .views.about_view import AboutView
from .models.app_state import AppState
from .utils.theme import ThemeManager
from .utils.helpers import log

if TYPE_CHECKING:  # pragma: no cover - used for type hints only
    from .views.quick_settings import QuickSettingsDialog
    from .views.force_quit_dialog import ForceQuitDialog
    from .views.security_dialog import SecurityDialog


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

        # Set application icon
        self._set_app_icon()

        # Set minimum window size
        self.window.minsize(800, 600)

        # Theme manager
        self.theme = ThemeManager(config=self.config)
        self.theme.apply_theme(self.config.get("theme", {}))
        log("Initialized theme manager")

        # Initialize views dict
        self.views: Dict[str, ctk.CTkFrame] = {}
        self.current_view: Optional[str] = None
        self.quick_settings_window: "QuickSettingsDialog | None" = None
        self.force_quit_window: "ForceQuitDialog | None" = None
        self.security_center_window: "SecurityDialog | None" = None
        self.dialogs: list[object] = []

        # Setup UI
        self._setup_ui()

        # Bind events
        self._bind_events()

        # Load initial view
        self.switch_view("home")

    def _set_app_icon(self) -> None:
        """Set the window and dock icon to the CoolBox logo."""
        icon_path = Path(__file__).resolve().parent.parent / "assets" / "images" / "Coolbox_logo.png"
        try:
            image = Image.open(icon_path)
            self._icon_photo = ImageTk.PhotoImage(image)
            self.window.iconphoto(True, self._icon_photo)

            if sys.platform.startswith("win"):
                try:
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ico")
                    image.save(tmp, format="ICO")
                    tmp.close()
                    self.window.iconbitmap(tmp.name)
                    try:
                        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CoolBox")
                    except Exception:  # pragma: no cover - best effort
                        pass
                    self._temp_icon = tmp.name
                except Exception as exc:  # pragma: no cover - optional feature
                    log(f"Failed to set taskbar icon: {exc}")
        except Exception as exc:  # pragma: no cover - best effort
            log(f"Failed to set window icon: {exc}")

        if sys.platform == "darwin":
            try:
                from AppKit import NSApplication, NSImage

                ns_image = NSImage.alloc().initByReferencingFile_(str(icon_path))
                NSApplication.sharedApplication().setApplicationIconImage_(ns_image)
            except Exception as exc:  # pragma: no cover - optional feature
                log(f"Failed to set dock icon: {exc}")

    def get_icon_photo(self):
        """Return the cached application icon if available."""
        return getattr(self, "_icon_photo", None)

    def _setup_ui(self):
        """Setup the main UI layout"""
        # Create main container
        self.main_container = ctk.CTkFrame(self.window, corner_radius=0)
        self.main_container.pack(fill="both", expand=True)

        # Create menu bar if enabled
        self.menu_bar: MenuBar | None = None
        if self.config.get("show_menu", True):
            self.menu_bar = MenuBar(self.window, self)

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
            self.status_bar = StatusBar(self.main_container, self)
            self.status_bar.pack(fill="x", side="bottom")

        # Initialize views
        self._init_views()
        self.refresh_recent_files()
        if self.menu_bar is not None:
            self.menu_bar.refresh_toggles()
        self.update_fonts()
        self.update_theme()

    def update_ui_visibility(self) -> None:
        """Show or hide optional UI elements based on config."""
        if self.config.get("show_toolbar", True):
            if self.toolbar is None:
                self.toolbar = Toolbar(self.main_container, self)
                self.toolbar.pack(fill="x", padx=0, pady=0)
        elif self.toolbar is not None:
            self.toolbar.destroy()
            self.toolbar = None

        if self.config.get("show_menu", True):
            if self.menu_bar is None:
                self.menu_bar = MenuBar(self.window, self)
            self.menu_bar.update_recent_files()
        elif self.menu_bar is not None:
            self.window.config(menu=None)
            self.menu_bar = None
        if self.menu_bar is not None:
            self.menu_bar.refresh_toggles()

        if self.config.get("show_statusbar", True):
            if self.status_bar is None:
                self.status_bar = StatusBar(self.main_container, self)
                self.status_bar.pack(fill="x", side="bottom")
        elif self.status_bar is not None:
            self.status_bar.destroy()
            self.status_bar = None

    def refresh_recent_files(self) -> None:
        """Update recent file menus across the UI."""
        if self.toolbar is not None:
            self.toolbar.update_recent_files()
        if self.menu_bar is not None:
            self.menu_bar.update_recent_files()

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
        self.window.bind("<Control-q>", lambda e: self.open_quick_settings())
        self.window.bind("<F11>", lambda e: self.toggle_fullscreen())
        self.window.bind("<Control-Alt-f>", lambda e: self.open_force_quit())

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
        if self.menu_bar is not None:
            self.menu_bar.refresh_toggles()

    def open_quick_settings(self) -> None:
        """Launch the Quick Settings dialog or focus the existing one."""
        from .views.quick_settings import QuickSettingsDialog

        if self.quick_settings_window is not None and self.quick_settings_window.winfo_exists():
            self.quick_settings_window.focus()
            return

        self.quick_settings_window = QuickSettingsDialog(self)
        self.quick_settings_window.protocol(
            "WM_DELETE_WINDOW", self._on_quick_settings_closed
        )

    def open_force_quit(self) -> None:
        """Launch the Force Quit dialog or focus the existing one."""
        from .views.force_quit_dialog import ForceQuitDialog

        if self.force_quit_window is not None and self.force_quit_window.winfo_exists():
            self.force_quit_window.focus()
            return

        self.force_quit_window = ForceQuitDialog(self)
        self.force_quit_window.protocol(
            "WM_DELETE_WINDOW", self._on_force_quit_closed
        )

    def open_security_center(self) -> None:
        """Launch the Security Center dialog with elevation when needed."""
        from .views.security_dialog import SecurityDialog
        from .utils.security import is_admin, launch_security_center
        from tkinter import messagebox

        if not is_admin():
            if not launch_security_center():
                messagebox.showerror(
                    "Security Center", "Failed to relaunch with admin rights"
                )
            return

        if (
            self.security_center_window is not None
            and self.security_center_window.winfo_exists()
        ):
            self.security_center_window.focus()
            return

        self.security_center_window = SecurityDialog(self)
        self.security_center_window.protocol(
            "WM_DELETE_WINDOW", self._on_security_center_closed
        )

    def register_dialog(self, dialog) -> None:
        """Track an open dialog for global updates."""
        if dialog not in self.dialogs:
            self.dialogs.append(dialog)

    def unregister_dialog(self, dialog) -> None:
        """Remove *dialog* from the tracked list."""
        if dialog in self.dialogs:
            self.dialogs.remove(dialog)

    def update_fonts(self) -> None:
        """Refresh fonts for all views and dialogs."""
        for view in self.views.values():
            if hasattr(view, "refresh_fonts"):
                view.refresh_fonts()
        if self.sidebar is not None and hasattr(self.sidebar, "refresh_fonts"):
            self.sidebar.refresh_fonts()
        if self.toolbar is not None and hasattr(self.toolbar, "refresh_fonts"):
            self.toolbar.refresh_fonts()
        if self.status_bar is not None and hasattr(self.status_bar, "refresh_fonts"):
            self.status_bar.refresh_fonts()
        if self.menu_bar is not None and hasattr(self.menu_bar, "refresh_fonts"):
            self.menu_bar.refresh_fonts()
        for dlg in list(self.dialogs):
            if dlg.winfo_exists():
                dlg.refresh_fonts()
            else:
                self.dialogs.remove(dlg)

    def update_theme(self) -> None:
        """Refresh theme colors across views and dialogs."""
        for view in self.views.values():
            if hasattr(view, "refresh_theme"):
                view.refresh_theme()
        if self.sidebar is not None and hasattr(self.sidebar, "refresh_theme"):
            self.sidebar.refresh_theme()
        if self.toolbar is not None and hasattr(self.toolbar, "refresh_theme"):
            self.toolbar.refresh_theme()
        if self.status_bar is not None and hasattr(self.status_bar, "refresh_theme"):
            self.status_bar.refresh_theme()
        if self.menu_bar is not None and hasattr(self.menu_bar, "refresh_theme"):
            self.menu_bar.refresh_theme()
        for dlg in list(self.dialogs):
            if dlg.winfo_exists() and hasattr(dlg, "refresh_theme"):
                dlg.refresh_theme()
            elif not dlg.winfo_exists():
                self.dialogs.remove(dlg)

    def _on_force_quit_closed(self) -> None:
        if self.force_quit_window is not None and self.force_quit_window.winfo_exists():
            self.force_quit_window.destroy()
        self.force_quit_window = None

    def _on_quick_settings_closed(self) -> None:
        if self.quick_settings_window is not None and self.quick_settings_window.winfo_exists():
            self.quick_settings_window.destroy()
        self.quick_settings_window = None

    def _on_security_center_closed(self) -> None:
        if self.security_center_window is not None and self.security_center_window.winfo_exists():
            self.security_center_window.destroy()
        self.security_center_window = None

    def _on_closing(self):
        """Handle window closing event"""
        # Save configuration
        self.config.set("window_width", self.window.winfo_width())
        self.config.set("window_height", self.window.winfo_height())
        self.config.set("theme", self.theme.get_theme())
        self.config.save()

        log("Application closing")

        if hasattr(self, "_temp_icon"):
            try:
                Path(self._temp_icon).unlink(missing_ok=True)
            except Exception:
                pass

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
