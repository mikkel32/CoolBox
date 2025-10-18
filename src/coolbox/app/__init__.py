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
from typing import Any, Optional, TYPE_CHECKING, Protocol, TypeGuard
from collections.abc import MutableMapping
from pathlib import Path
import sys
import logging
import tkinter as tk
from tkinter import messagebox

from ..config import Config
from ..ui.components.layout import MenuBar, Sidebar, StatusBar, Toolbar
from ..models.app_state import AppState
from ..utils.theme import ThemeManager
from ..utils.thread_manager import ThreadManager

from .icon import set_app_icon
from .layout import setup_ui
from .error_handler import install as install_error_handlers
from .infrastructure import AppInfrastructure

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - used for type hints only
    from customtkinter import CTkFrame as _CTkFrame

    from ..ui.views.dialogs.quick_settings import QuickSettingsDialog
    from ..ui.views.dialogs.force_quit import ForceQuitDialog
    from ..ui.views.dialogs.security import SecurityDialog
else:
    _CTkFrame = ctk.CTkFrame


class _FontsRefreshable(Protocol):
    def refresh_fonts(self) -> None: ...


class _ThemeRefreshable(Protocol):
    def refresh_theme(self) -> None: ...


def _supports_fonts(value: object) -> TypeGuard[_FontsRefreshable]:
    return hasattr(value, "refresh_fonts")


def _supports_theme(value: object) -> TypeGuard[_ThemeRefreshable]:
    return hasattr(value, "refresh_theme")


class CoolBoxApp:
    """Main application class"""

    def __init__(self):
        """Initialize the application"""
        # Application infrastructure holds service wiring and lifecycle hooks.
        self.infrastructure = AppInfrastructure(self)

        # Load core services from the infrastructure container.
        self.config = self.infrastructure.require("config", Config)
        self.state = self.infrastructure.require("app_state", AppState)
        self.thread_manager = self.infrastructure.require("thread_manager", ThreadManager)
        # Background threads: process manager and logger with monitoring
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
        self._icon_photo: Any | None = None
        self._temp_icon: str | None = None
        try:
            icon_photo, temp_icon = set_app_icon(self.window)
            self._icon_photo = icon_photo
            self._temp_icon = temp_icon
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Icon setup failed: %s", exc)

        # Set minimum window size
        self.window.minsize(
            self.config.get("window_min_width", 800),
            self.config.get("window_min_height", 800),
        )

        # Theme manager
        self.theme = self.infrastructure.require("theme_manager", ThemeManager)
        self.theme.apply_theme(self.config.get("theme", {}))
        logger.info("Initialized theme manager")

        # Initialize views dict
        self.main_container: _CTkFrame | None = None
        self.content_area: _CTkFrame | None = None
        self.view_container: _CTkFrame | None = None
        self.sidebar: Sidebar | None = None
        self.toolbar: Toolbar | None = None
        self.menu_bar: MenuBar | None = None
        self.status_bar: StatusBar | None = None
        self.views: MutableMapping[str, _CTkFrame] = {}
        self.current_view: Optional[str] = None
        self.quick_settings_window: QuickSettingsDialog | None = None
        self.force_quit_window: ForceQuitDialog | None = None
        self.security_center_window: SecurityDialog | None = None
        self.dialogs: list[tk.Misc] = []

        # Setup UI
        try:
            setup_ui(self)
        except Exception as exc:  # pragma: no cover - critical failure
            logger.error("UI setup failed: %s", exc)
            raise

        if not all(
            (
                self.main_container,
                self.content_area,
                self.view_container,
                self.sidebar,
                self.views,
            )
        ):
            raise RuntimeError("UI setup failed to initialize layout components")

        # Wrap created views in the infrastructure-backed registry for
        # automatic refresh tracking.
        self.views = self.infrastructure.create_view_store(dict(self.views))

        # Register core UI elements for font/theme updates.
        self._register_refreshable_components()

        # The setup created non-optional widgets; help static type checkers.
        assert self.main_container is not None
        assert self.content_area is not None
        assert self.view_container is not None
        assert self.sidebar is not None

        # Bind events
        self._bind_events()

        # Load initial view
        self.switch_view("home")

    def get_icon_photo(self):
        """Return the cached application icon if available."""
        return getattr(self, "_icon_photo", None)

    def update_ui_visibility(self) -> None:
        """Show or hide optional UI elements based on config."""
        if self.main_container is None:
            logger.debug("Main container unavailable; skipping UI visibility update")
            return
        if self.config.get("show_toolbar", True):
            if self.toolbar is None:
                self.toolbar = Toolbar(self.main_container, self)
                self.toolbar.pack(fill="x", padx=0, pady=0)
                self.infrastructure.register_refreshable(self.toolbar, fonts=True, theme=True)
        elif self.toolbar is not None:
            self.infrastructure.unregister_refreshable(self.toolbar)
            self.toolbar.destroy()
            self.toolbar = None

        if self.config.get("show_menu", True):
            if self.menu_bar is None:
                self.menu_bar = MenuBar(self.window, self)
                self.infrastructure.register_refreshable(self.menu_bar, fonts=True, theme=True)
            self.menu_bar.update_recent_files()
        elif self.menu_bar is not None:
            self.window.configure(menu="")
            self.infrastructure.unregister_refreshable(self.menu_bar)
            self.menu_bar = None
        if self.menu_bar is not None:
            self.menu_bar.refresh_toggles()

        if self.config.get("show_statusbar", True):
            if self.status_bar is None:
                self.status_bar = StatusBar(self.main_container, self)
                self.status_bar.pack(fill="x", side="bottom")
                self.infrastructure.register_refreshable(self.status_bar, fonts=True, theme=True)
        elif self.status_bar is not None:
            self.infrastructure.unregister_refreshable(self.status_bar)
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
        if self.sidebar is not None:
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
        from ..ui.views.dialogs.quick_settings import QuickSettingsDialog

        if self.quick_settings_window is not None and self.quick_settings_window.winfo_exists():
            self.quick_settings_window.focus()
            return

        dialog = QuickSettingsDialog(self)
        self.quick_settings_window = dialog
        dialog.protocol("WM_DELETE_WINDOW", self._on_quick_settings_closed)

    def open_force_quit(self) -> None:
        """Launch the Force Quit dialog or focus the existing one."""
        try:
            from ..ui.views.dialogs.force_quit import ForceQuitDialog
        except Exception as exc:  # pragma: no cover - runtime import error
            logger.warning("Failed to import ForceQuitDialog: %s", exc)
            messagebox.showerror("Force Quit", f"Failed to open dialog: {exc}")
            return

        if self.force_quit_window is not None and self.force_quit_window.winfo_exists():
            self.force_quit_window.focus()
            return

        try:
            dialog = ForceQuitDialog(self)
            self.force_quit_window = dialog
            dialog.bind("<Destroy>", lambda _e: setattr(self, "force_quit_window", None))
        except Exception as exc:  # pragma: no cover - runtime init error
            logger.warning("Failed to create ForceQuitDialog: %s", exc)
            messagebox.showerror("Force Quit", f"Failed to open dialog: {exc}")
            self.force_quit_window = None

    def open_security_center(self) -> None:
        """Open the Security Center dialog."""
        from ..ui.views.dialogs.security import SecurityDialog
        import tkinter as tk
        from coolbox.utils import security

        if not security.is_admin():
            if security.relaunch_security_center():
                return
            messagebox.showwarning(
                "Security Center", "Administrator rights required."
            )
            return

        if self.security_center_window is not None:
            current_top = self.security_center_window.winfo_toplevel()
            if current_top.winfo_exists():
                current_top.focus()
                return
            self.security_center_window = None

        top = tk.Toplevel(self.window)
        dialog = SecurityDialog(top)
        self.security_center_window = dialog
        top.protocol("WM_DELETE_WINDOW", self._on_security_center_closed)

    def register_dialog(self, dialog: tk.Misc) -> None:
        """Track an open dialog for global updates."""
        if dialog not in self.dialogs:
            self.dialogs.append(dialog)
        self.infrastructure.register_refreshable(dialog, fonts=True, theme=True)

    def unregister_dialog(self, dialog: tk.Misc) -> None:
        """Remove *dialog* from the tracked list."""
        if dialog in self.dialogs:
            self.dialogs.remove(dialog)
        self.infrastructure.unregister_refreshable(dialog)

    def update_fonts(self) -> None:
        """Refresh fonts for all views and dialogs."""
        for target in self.infrastructure.iter_refreshables("fonts"):
            if _supports_fonts(target):
                target.refresh_fonts()

    def update_theme(self) -> None:
        """Refresh theme colors across views and dialogs."""
        for target in self.infrastructure.iter_refreshables("theme"):
            if _supports_theme(target):
                target.refresh_theme()

    def _on_quick_settings_closed(self) -> None:
        if self.quick_settings_window is not None and self.quick_settings_window.winfo_exists():
            self.quick_settings_window.destroy()
        self.quick_settings_window = None

    def _on_security_center_closed(self) -> None:
        if self.security_center_window is not None:
            top = self.security_center_window.winfo_toplevel()
            if top.winfo_exists():
                top.destroy()
        self.security_center_window = None

    def _on_closing(self):
        """Handle window closing event"""
        # Save configuration
        self.config.set("window_width", self.window.winfo_width())
        self.config.set("window_height", self.window.winfo_height())
        self.config.set("theme", self.theme.get_theme())
        self.config.save()

        logger.info("Application closing")

        if self._temp_icon:
            try:
                Path(self._temp_icon).unlink(missing_ok=True)
            except Exception:
                pass

        self.infrastructure.shutdown()

        # Destroy window
        self.window.destroy()
        sys.exit(0)

    def run(self):
        """Start the application"""
        logger.info("Starting main loop")
        self.window.mainloop()

    def destroy(self):
        """Destroy the application window."""
        self.infrastructure.shutdown()
        if self.window.winfo_exists():
            self.window.destroy()
        logger.info("Window destroyed")

    def _register_refreshable_components(self) -> None:
        """Register core widgets with the infrastructure refresh registries."""
        self.infrastructure.register_refreshable(self.sidebar, fonts=True, theme=True)
        self.infrastructure.register_refreshable(self.toolbar, fonts=True, theme=True)
        self.infrastructure.register_refreshable(self.menu_bar, fonts=True, theme=True)
        self.infrastructure.register_refreshable(self.status_bar, fonts=True, theme=True)
        for view in self.views.values():
            self.infrastructure.register_refreshable(view, fonts=True, theme=True)
