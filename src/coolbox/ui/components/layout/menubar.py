"""Application menu bar."""
from __future__ import annotations

import tkinter as tk
import customtkinter as ctk


class MenuBar:
    """Application menu bar with view toggles and recent files."""

    def __init__(self, window: ctk.CTk, app):
        self.app = app
        size = int(app.config.get("font_size", 14))
        self.font = ctk.CTkFont(size=size)
        self.menu = tk.Menu(window, font=self.font)
        self._build_menus()
        window.config(menu=self.menu)

    # ------------------------------------------------------------------
    def _build_menus(self) -> None:
        self.menus: list[tk.Menu] = []
        file_menu = tk.Menu(self.menu, tearoff=0, font=self.font)
        file_menu.add_command(label="Open", command=self._open)
        file_menu.add_command(label="Save", command=self._save)

        self.recent_menu = tk.Menu(file_menu, tearoff=0, font=self.font)
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
        self.menus.append(file_menu)

        view_menu = tk.Menu(self.menu, tearoff=0, font=self.font)
        self.toolbar_var = tk.BooleanVar(
            value=self.app.config.get("show_toolbar", True)
        )
        self.status_var = tk.BooleanVar(
            value=self.app.config.get("show_statusbar", True)
        )
        self.fullscreen_var = tk.BooleanVar(
            value=self.app.window.attributes("-fullscreen")
        )
        self.developer_var = tk.BooleanVar(
            value=self.app.config.get("developer_mode", False)
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
        view_menu.add_checkbutton(
            label="Developer Mode",
            variable=self.developer_var,
            command=self._toggle_developer_mode,
        )
        self.menu.add_cascade(label="View", menu=view_menu)
        self.menus.append(view_menu)

        help_menu = tk.Menu(self.menu, tearoff=0, font=self.font)
        help_menu.add_command(label="About", command=lambda: self.app.switch_view("about"))
        self.menu.add_cascade(label="Help", menu=help_menu)
        self.menus.append(help_menu)

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
        self.developer_var.set(self.app.config.get("developer_mode", False))

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

    def _toggle_developer_mode(self) -> None:
        self.app.config.set("developer_mode", self.developer_var.get())
        try:
            self.app.config.save()
        except Exception:
            pass

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
        from coolbox.utils.system_utils import open_path

        open_path(path)
        self.app.config.add_recent_file(path)
        self.app.refresh_recent_files()
        if self.app.status_bar is not None:
            self.app.status_bar.set_message(f"Opened: {path}", "info")

    def _toggle_fullscreen(self) -> None:
        self.app.toggle_fullscreen()
        self.fullscreen_var.set(self.app.window.attributes("-fullscreen"))

    def refresh_fonts(self) -> None:
        """Update menu fonts from the current configuration."""
        size = int(self.app.config.get("font_size", 14))
        self.font.configure(size=size)
        self.menu.configure(font=self.font)
        for menu in self.menus:
            menu.configure(font=self.font)
        self.update_recent_files()

    def refresh_theme(self) -> None:
        """Refresh menu highlight colors from the current theme."""
        accent = self.app.theme.get_theme().get("accent_color", "#1faaff")
        self.menu.configure(activebackground=accent, activeforeground="white")
        for menu in self.menus:
            menu.configure(activebackground=accent, activeforeground="white")
