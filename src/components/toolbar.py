"""
Toolbar component with common actions
"""
import customtkinter as ctk
from tkinter import filedialog, messagebox

from ..utils import file_manager
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
        if filename:
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
            self.app.status_bar.set_message(f"Saved: {filename}", "success")

    def _copy(self):
        """Copy action"""
        # This would copy from the current view
        self.app.status_bar.set_message("Copied to clipboard", "info")

    def _cut(self):
        """Cut action"""
        self.app.status_bar.set_message("Cut to clipboard", "info")

    def _paste(self):
        """Paste action"""
        try:
            pyperclip.paste()
            self.app.status_bar.set_message("Pasted from clipboard", "info")
        except Exception:
            self.app.status_bar.set_message("Nothing to paste", "warning")

    def _search(self):
        """Perform search"""
        query = self.search_var.get()
        if query:
            self.app.status_bar.set_message(f"Searching for: {query}", "info")
            # Implement actual search functionality
        else:
            self.app.status_bar.set_message("Enter search query", "warning")
