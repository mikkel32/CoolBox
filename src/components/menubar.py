"""Application menu bar."""
from __future__ import annotations

import tkinter as tk
import customtkinter as ctk


class MenuBar:
    """Application menu bar with view toggles and recent files."""

    def __init__(self, window: ctk.CTk, app):
        self.app = app
        self.menu = tk.Menu(window)
        self._build_menus()
        window.config(menu=self.menu)

    # ------------------------------------------------------------------
    def _build_menus(self) -> None:
        file_menu = tk.Menu(self.menu, tearoff=0)
        file_menu.add_command(label="Open", command=self._open)
        file_menu.add_command(label="Save", command=self._save)

        self.recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Open Recent", menu=self.recent_menu)
        self.update_recent_files()

        file_menu.add_separator()
        file_menu.add_command(label="Quick Settings", command=self._open_quick_settings)
        file_menu.add_command(
            label="Settings", command=lambda: self.app.switch_view("settings")
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.app._on_closing)
        self.menu.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(self.menu, tearoff=0)
        self.toolbar_var = tk.BooleanVar(
            value=self.app.config.get("show_toolbar", True)
        )
        self.status_var = tk.BooleanVar(
            value=self.app.config.get("show_statusbar", True)
        )
        self.fullscreen_var = tk.BooleanVar(
            value=self.app.window.attributes("-fullscreen")
        )

        view_menu.add_checkbutton(
            label="Toolbar", variable=self.toolbar_var, command=self._toggle_toolbar
        )
        view_menu.add_checkbutton(
            label="Status Bar", variable=self.status_var, command=self._toggle_statusbar
        )
        view_menu.add_checkbutton(
            label="Full Screen", variable=self.fullscreen_var, command=self._toggle_fullscreen
        )
        self.menu.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(self.menu, tearoff=0)
        help_menu.add_command(label="About", command=lambda: self.app.switch_view("about"))
        self.menu.add_cascade(label="Help", menu=help_menu)

    # ------------------------------------------------------------------
    def _open_quick_settings(self) -> None:
        """Show the quick settings dialog."""
        self.app.open_quick_settings()

    # ------------------------------------------------------------------
    def refresh_toggles(self) -> None:
        """Sync toggle states with current config."""
        self.toolbar_var.set(self.app.config.get("show_toolbar", True))
        self.status_var.set(self.app.config.get("show_statusbar", True))
        self.fullscreen_var.set(self.app.window.attributes("-fullscreen"))

    # ------------------------------------------------------------------
    def _call_toolbar(self, name: str) -> None:
        toolbar = self.app.toolbar
        if toolbar is not None and hasattr(toolbar, name):
            getattr(toolbar, name)()

    def _open(self) -> None:
        self._call_toolbar("_open_file")

    def _save(self) -> None:
        self._call_toolbar("_save_file")

    def _toggle_toolbar(self) -> None:
        self.app.config.set("show_toolbar", self.toolbar_var.get())
        self.app.update_ui_visibility()

    def _toggle_statusbar(self) -> None:
        self.app.config.set("show_statusbar", self.status_var.get())
        self.app.update_ui_visibility()

    # ------------------------------------------------------------------
    def update_recent_files(self) -> None:
        """Refresh the recent files submenu."""
        self.recent_menu.delete(0, "end")
        files = self.app.config.get("recent_files", [])
        if files:
            for path in files:
                self.recent_menu.add_command(
                    label=path, command=lambda p=path: self._open_recent(p)
                )
        else:
            self.recent_menu.add_command(label="(Empty)", state="disabled")

    def _open_recent(self, path: str) -> None:
        """Open a recently used file."""
        from ..utils.helpers import open_path

        open_path(path)
        self.app.config.add_recent_file(path)
        self.app.refresh_recent_files()
        if self.app.status_bar is not None:
            self.app.status_bar.set_message(f"Opened: {path}", "info")

    def _toggle_fullscreen(self) -> None:
        self.app.toggle_fullscreen()
        self.fullscreen_var.set(self.app.window.attributes("-fullscreen"))
