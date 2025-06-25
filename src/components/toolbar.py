"""
Toolbar component with common actions
"""

import customtkinter as ctk
from tkinter import filedialog
from pathlib import Path

from ..utils import file_manager, open_path
import pyperclip
from .tooltip import Tooltip


class Toolbar(ctk.CTkFrame):
    """Application toolbar"""

    def __init__(self, parent, app):
        """Initialize toolbar"""
        super().__init__(parent, height=50, corner_radius=0)
        self.app = app
        self._tooltips: list[Tooltip] = []

        # Prevent frame from shrinking
        self.pack_propagate(False)

        # Create toolbar items
        self._create_toolbar_items()
        self.update_recent_files()

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
            left_frame, "☰", "Toggle Sidebar", self.app.toggle_sidebar
        ).pack(side="left", padx=5)

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
        )
        self.recent_menu.pack(side="right", padx=5)

        # Search box
        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(
            right_frame,
            placeholder_text="Search...",
            textvariable=self.search_var,
            width=200,
        )
        self.search_entry.pack(side="right", padx=5)

        # Search button
        self._create_button(right_frame, "🔍", "Search", self._search).pack(
            side="right", padx=5
        )

    def _create_button(self, parent, icon: str, tooltip: str, command) -> ctk.CTkButton:
        """Create a toolbar button"""
        btn = ctk.CTkButton(
            parent,
            text=icon,
            width=40,
            height=30,
            command=command,
            font=ctk.CTkFont(size=16),
        )
        tip = Tooltip(self, tooltip)
        btn.bind("<Enter>", lambda e, t=tip: self._on_hover(t, e))
        btn.bind("<Leave>", lambda e, t=tip: t.hide())
        self._tooltips.append(tip)
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
        """Perform a simple filename search and show results."""
        query = self.search_var.get().strip()
        if not query:
            if self.app.status_bar is not None:
                self.app.status_bar.set_message("Enter search query", "warning")
            return

        if self.app.status_bar is not None:
            self.app.status_bar.set_message(f"Searching for: {query}", "info")

        directory = filedialog.askdirectory(
            title="Select folder to search", parent=self
        )
        if not directory:
            return

        matches = [p for p in Path(directory).rglob(f"*{query}*") if p.is_file()]

        window = ctk.CTkToplevel(self)
        window.title(f"Search results for '{query}'")
        window.geometry("600x400")

        if not matches:
            ctk.CTkLabel(window, text="No results found").pack(padx=20, pady=20)
            return

        ctk.CTkLabel(
            window,
            text=f"Results ({len(matches)})",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(pady=(10, 5))

        results_frame = ctk.CTkScrollableFrame(window)
        results_frame.pack(fill="both", expand=True, padx=10, pady=10)

        for path in matches:
            ctk.CTkButton(
                results_frame,
                text=str(path),
                anchor="w",
                command=lambda p=path: open_path(str(p)),
            ).pack(fill="x", pady=2)

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
