"""
Toolbar component with common actions
"""
import customtkinter as ctk
from tkinter import filedialog
from pathlib import Path

from ..utils import file_manager, open_path
import pyperclip


class Toolbar(ctk.CTkFrame):
    """Application toolbar"""

    def __init__(self, parent, app):
        """Initialize toolbar"""
        super().__init__(parent, height=50, corner_radius=0)
        self.app = app

        # Prevent frame from shrinking
        self.pack_propagate(False)

        # Create toolbar items
        self._create_toolbar_items()

    def _create_toolbar_items(self):
        """Create toolbar buttons and items"""
        # Left side buttons
        left_frame = ctk.CTkFrame(self, fg_color="transparent")
        left_frame.pack(side="left", padx=10)

        # File operations
        self._create_button(left_frame, "📁", "Open File", self._open_file).pack(side="left", padx=5)
        self._create_button(left_frame, "💾", "Save", self._save_file).pack(side="left", padx=5)
        self._create_button(left_frame, "📋", "Copy", self._copy).pack(side="left", padx=5)
        self._create_button(left_frame, "✂️", "Cut", self._cut).pack(side="left", padx=5)
        self._create_button(left_frame, "📌", "Paste", self._paste).pack(side="left", padx=5)

        # Separator
        separator = ctk.CTkFrame(self, width=2, fg_color="gray50")
        separator.pack(side="left", fill="y", padx=10, pady=10)

        # Right side items
        right_frame = ctk.CTkFrame(self, fg_color="transparent")
        right_frame.pack(side="right", padx=10)

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
        self._create_button(right_frame, "🔍", "Search", self._search).pack(side="right", padx=5)

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
        # Could add tooltip functionality here
        return btn

    def _open_file(self):
        """Open file dialog"""
        filename = file_manager.pick_file()
        if filename and self.app.status_bar is not None:
            self.app.status_bar.set_message(f"Opened: {filename}", "info")
            self.app.config.add_recent_file(filename)

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

    def _search(self):
        """Perform a simple filename search and show results."""
        query = self.search_var.get().strip()
        if not query:
            if self.app.status_bar is not None:
                self.app.status_bar.set_message("Enter search query", "warning")
            return

        if self.app.status_bar is not None:
            self.app.status_bar.set_message(f"Searching for: {query}", "info")

        directory = filedialog.askdirectory(title="Select folder to search", parent=self)
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
