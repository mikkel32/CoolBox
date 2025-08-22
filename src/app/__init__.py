"""
CoolBox Application Class
Manages the main application window and navigation
"""
from __future__ import annotations

try:
    import customtkinter as ctk
except ImportError:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_customtkinter

    ctk = ensure_customtkinter()
from typing import Dict, Optional, TYPE_CHECKING
from pathlib import Path
import sys
import logging
import threading
from tkinter import messagebox

from ..config import Config
from ..components.toolbar import Toolbar
from ..components.status_bar import StatusBar
from ..components.menubar import MenuBar
from ..models.app_state import AppState
from ..utils.theme import ThemeManager
from ..utils.thread_manager import ThreadManager

from .icon import set_app_icon
from .layout import setup_ui
from .error_handler import install as install_error_handlers

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - used for type hints only
    from ..views.quick_settings import QuickSettingsDialog
    from ..views.force_quit_dialog import ForceQuitDialog
    from ..views.security_dialog import SecurityDialog


class CoolBoxApp:
    """Main application class"""

    def __init__(self):
        """Initialize the application"""
        # Load configuration
        self.config = Config()
        self.state = AppState()
        # Background threads: process manager and logger with monitoring
        self.thread_manager = ThreadManager()
        self.thread_manager.start()

        # Set appearance
        ctk.set_appearance_mode(self.config.get("appearance_mode", "dark"))
        ctk.set_default_color_theme(self.config.get("color_theme", "blue"))

        # Create main window
        self.window = ctk.CTk()
        self.window.title("CoolBox - Modern Desktop App")
        self.window.geometry(
            f"{self.config.get('window_width', 1200)}x{self.config.get('window_height', 1000)}"
        )

        # Global error handling and warning capture
        install_error_handlers(self.window)

        # Set application icon
        try:
            self._icon_photo, self._temp_icon = set_app_icon(self.window)
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Icon setup failed: %s", exc)
            self._icon_photo = None
            self._temp_icon = None

        # Set minimum window size
        self.window.minsize(
            self.config.get("window_min_width", 800),
            self.config.get("window_min_height", 800),
        )

        # Theme manager
        self.theme = ThemeManager(config=self.config)
        self.theme.apply_theme(self.config.get("theme", {}))
        logger.info("Initialized theme manager")

        # Initialize views dict
        self.views: Dict[str, ctk.CTkFrame] = {}
        self.current_view: Optional[str] = None
        self.quick_settings_window: "QuickSettingsDialog | None" = None
        self.force_quit_window: "ForceQuitDialog | None" = None
        self.security_center_window: "SecurityDialog | None" = None
        self.dialogs: list[object] = []

        # Setup UI
        try:
            setup_ui(self)
        except Exception as exc:  # pragma: no cover - critical failure
            logger.error("UI setup failed: %s", exc)
            raise

        # Bind events
        self._bind_events()

        # Load initial view
        self.switch_view("home")

    def get_icon_photo(self):
        """Return the cached application icon if available."""
        return getattr(self, "_icon_photo", None)

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

        logger.info("Switched view to %s", view_name)

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
        from ..views.quick_settings import QuickSettingsDialog

        if self.quick_settings_window is not None and self.quick_settings_window.winfo_exists():
            self.quick_settings_window.focus()
            return

        self.quick_settings_window = QuickSettingsDialog(self)
        self.quick_settings_window.protocol(
            "WM_DELETE_WINDOW", self._on_quick_settings_closed
        )

    def open_force_quit(self) -> None:
        """Launch the Force Quit dialog or focus the existing one."""
        if threading.current_thread() is not threading.main_thread():
            self.window.after(0, self.open_force_quit)
            return

        try:
            from ..views.force_quit_dialog import ForceQuitDialog
        except Exception as exc:  # pragma: no cover - runtime import error
            logger.warning("Failed to import ForceQuitDialog: %s", exc)
            messagebox.showerror("Force Quit", f"Failed to open dialog: {exc}")
            return

        if self.force_quit_window is not None and self.force_quit_window.winfo_exists():
            self.force_quit_window.focus()
            return

        try:
            self.force_quit_window = ForceQuitDialog(self)
            self.force_quit_window.bind(
                "<Destroy>", lambda _e: setattr(self, "force_quit_window", None)
            )
        except Exception as exc:  # pragma: no cover - runtime init error
            logger.warning("Failed to create ForceQuitDialog: %s", exc)
            messagebox.showerror("Force Quit", f"Failed to open dialog: {exc}")
            self.force_quit_window = None

    def open_security_center(self) -> None:
        """Open the Security Center dialog."""
        from ..views.security_dialog import SecurityDialog
        import tkinter as tk
        from src.utils import security

        if not security.is_admin():
            if security.relaunch_security_center():
                return
            messagebox.showwarning(
                "Security Center", "Administrator rights required."
            )
            return

        if (
            self.security_center_window is not None
            and self.security_center_window.winfo_exists()
        ):
            self.security_center_window.focus()
            return

        top = tk.Toplevel(self.window)
        SecurityDialog(top)
        self.security_center_window = top
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

        logger.info("Application closing")

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
        logger.info("Starting main loop")
        self.window.mainloop()

    def destroy(self):
        """Destroy the application window."""
        self.thread_manager.stop()
        self.window.destroy()
        logger.info("Window destroyed")
