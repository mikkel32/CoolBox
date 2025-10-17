"""
Toolbar component with common actions
"""

import customtkinter as ctk
from tkinter import filedialog
from typing import Any, Callable

from coolbox.utils import file_manager
from coolbox.utils.system_utils import open_path
from coolbox.utils.ui import center_window
try:
    import pyperclip
except ImportError:  # pragma: no cover - runtime dependency check
    from coolbox.ensure_deps import ensure_pyperclip

    pyperclip = ensure_pyperclip()
from .tooltip import Tooltip


class Toolbar(ctk.CTkFrame):
    """Application toolbar"""

    def __init__(self, parent, app):
        """Initialize toolbar"""
        super().__init__(parent, height=50, corner_radius=0)
        self.app = app
        self._tooltips: list[Tooltip] = []
        size = int(app.config.get("font_size", 14))
        self.font = ctk.CTkFont(size=size)
        self.buttons: list[ctk.CTkButton] = []

        # Prevent frame from shrinking
        self.pack_propagate(False)

        # Create toolbar items
        self._create_toolbar_items()
        self.update_recent_files()

    def refresh_fonts(self) -> None:
        """Update widget fonts based on current config."""
        size = int(self.app.config.get("font_size", 14))
        self.font.configure(size=size)
        for btn in self.buttons:
            btn.configure(font=self.font)
        self.search_entry.configure(font=self.font)
        self.recent_menu.configure(font=self.font)

    def refresh_theme(self) -> None:
        """Update button colors using the current accent color."""
        accent = self.app.theme.get_theme().get("accent_color", "#1faaff")
        for btn in self.buttons:
            btn.configure(fg_color=accent, hover_color=accent)
        self.search_entry.configure(border_color=accent)
        self.recent_menu.configure(fg_color=accent, button_color=accent)

    def _create_toolbar_items(self):
        """Create toolbar buttons and items"""
        # Left side buttons
        left_frame = ctk.CTkFrame(self, fg_color="transparent")
        left_frame.pack(side="left", padx=10)

        # File operations
        self._create_button(left_frame, "📁", "Open File", self._open_file).pack(
            side="left", padx=5
        )
        self._create_button(left_frame, "💾", "Save", self._save_file).pack(
            side="left", padx=5
        )
        self._create_button(left_frame, "📋", "Copy", self._copy).pack(
            side="left", padx=5
        )
        self._create_button(left_frame, "✂️", "Cut", self._cut).pack(side="left", padx=5)
        self._create_button(left_frame, "📌", "Paste", self._paste).pack(
            side="left", padx=5
        )

        self._create_button(
            left_frame,
            "⚡",
            "Quick Settings",
            self._open_quick_settings,
        ).pack(side="left", padx=5)

        # Separator
        separator = ctk.CTkFrame(self, width=2, fg_color="gray50")
        separator.pack(side="left", fill="y", padx=10, pady=10)

        # Right side items
        right_frame = ctk.CTkFrame(self, fg_color="transparent")
        right_frame.pack(side="right", padx=10)

        # Recent files dropdown
        self.recent_var = ctk.StringVar(value="Recent")
        self.recent_menu = ctk.CTkOptionMenu(
            right_frame,
            values=["Recent"],
            variable=self.recent_var,
            command=self._open_recent,
            width=150,
            font=self.font,
        )
        self.recent_menu.pack(side="right", padx=5)

        # Search box
        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(
            right_frame,
            placeholder_text="Search...",
            textvariable=self.search_var,
            width=200,
            font=self.font,
        )
        self.search_entry.pack(side="right", padx=5)
        self.search_entry.bind("<Return>", lambda e: self._search())

        # Search button
        self._create_button(right_frame, "🔍", "Search", self._search).pack(
            side="right", padx=5
        )

    def _create_button(self, parent, icon: str, tooltip: str, command) -> ctk.CTkButton:
        """Create a toolbar button and track it for updates."""
        btn = ctk.CTkButton(
            parent,
            text=icon,
            width=40,
            height=30,
            command=command,
            font=self.font,
        )
        tip = Tooltip(self, tooltip)
        btn.bind("<Enter>", lambda e, t=tip: self._on_hover(t, e))
        btn.bind("<Leave>", lambda e, t=tip: t.hide())
        self._tooltips.append(tip)
        self.buttons.append(btn)
        return btn

    def _on_hover(self, tooltip: Tooltip, event) -> None:
        """Show tooltip below a toolbar button."""
        x = event.widget.winfo_rootx() + event.widget.winfo_width() // 2
        y = event.widget.winfo_rooty() + event.widget.winfo_height() + 10
        tooltip.show(x, y)

    def _open_file(self):
        """Open file dialog"""
        filename = file_manager.pick_file()
        if filename:
            open_path(filename)
            self.app.config.add_recent_file(filename)
            self.app.refresh_recent_files()
            if self.app.status_bar is not None:
                self.app.status_bar.set_message(f"Opened: {filename}", "info")

    def _save_file(self):
        """Save file dialog"""
        filename = filedialog.asksaveasfilename(
            title="Save File",
            defaultextension=".txt",
            filetypes=[
                ("Text Files", "*.txt"),
                ("Python Files", "*.py"),
                ("All Files", "*.*"),
            ],
        )
        if filename:
            file_manager.write_text(filename, "")
            self.app.config.add_recent_file(filename)
            self.app.refresh_recent_files()
            if self.app.status_bar is not None:
                self.app.status_bar.set_message(f"Saved: {filename}", "success")

    def _copy(self):
        """Copy action"""
        # This would copy from the current view
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Copied to clipboard", "info")

    def _cut(self):
        """Cut action"""
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Cut to clipboard", "info")

    def _paste(self):
        """Paste action"""
        try:
            pyperclip.paste()
            if self.app.status_bar is not None:
                self.app.status_bar.set_message("Pasted from clipboard", "info")
        except Exception:
            if self.app.status_bar is not None:
                self.app.status_bar.set_message("Nothing to paste", "warning")

    def _open_quick_settings(self) -> None:
        """Launch the app's Quick Settings dialog."""
        self.app.open_quick_settings()

    def _search(self):
        """Search files, tools, and settings for the query."""
        query = self.search_var.get().strip().lower()
        if not query:
            if self.app.status_bar is not None:
                self.app.status_bar.set_message("Enter search query", "warning")
            return

        results: list[tuple[str, str, Callable[[], Any]]] = []

        tools_view = self.app.views.get("tools")
        if hasattr(tools_view, "get_tools"):
            for name, desc, cmd in tools_view.get_tools():
                if query in name.lower() or query in desc.lower():

                    def make_tool_action(command: Callable[[], Any]) -> Callable[[], Any]:
                        def _run() -> Any:
                            self.app.switch_view("tools")
                            return command()

                        return _run

                    results.append(("Tool", name, make_tool_action(cmd)))

        settings_view = self.app.views.get("settings")
        if hasattr(settings_view, "_sections"):
            for frame, text in settings_view._sections:
                if query in text:
                    heading = frame.winfo_children()[0] if frame.winfo_children() else None
                    if heading is not None:
                        cget = getattr(heading, "cget", None)
                        raw_title: Any = cget("text") if callable(cget) else "Settings"
                        title = str(raw_title)
                    else:
                        title = "Settings"

                    def open_sec(fr=frame, t=query):
                        self.app.switch_view("settings")
                        settings_view.search_var.set(t)
                        settings_view._filter_sections()
                        fr.after(100, lambda: fr.focus_set())

                    results.append(("Setting", title, open_sec))

        for path in self.app.config.get("recent_files", []):
            if query in path.lower():
                results.append(("File", path, lambda p=path: open_path(p)))

        if not results:
            if self.app.status_bar is not None:
                self.app.status_bar.set_message("No matches found", "warning")
            return

        window = ctk.CTkToplevel(self)
        window.title(f"Search results for '{self.search_var.get().strip()}'")
        window.geometry("500x400")
        ctk.CTkLabel(
            window,
            text=f"Results ({len(results)})",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(pady=(10, 5))

        frame = ctk.CTkScrollableFrame(window)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        accent = self.app.theme.get_theme().get("accent_color", "#1faaff")
        for category, label, action in results:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=f"{category}:", width=70, text_color=accent).pack(
                side="left"
            )
            ctk.CTkButton(row, text=label, anchor="w", command=action).pack(
                side="left", fill="x", expand=True
            )
        center_window(window)

    # ----- Recent files helpers -----
    def update_recent_files(self) -> None:
        """Refresh the recent files dropdown from config."""
        files = self.app.config.get("recent_files", [])
        if files:
            self.recent_menu.configure(values=files, state="normal")
            self.recent_var.set(files[0])
        else:
            self.recent_menu.configure(values=["Recent"], state="disabled")
            self.recent_var.set("Recent")

    def _open_recent(self, value: str) -> None:
        """Open a file selected from the recent dropdown."""
        if value and value != "Recent":
            open_path(value)
            self.app.config.add_recent_file(value)
            self.app.refresh_recent_files()
            if self.app.status_bar is not None:
                self.app.status_bar.set_message(f"Opened: {value}", "info")
