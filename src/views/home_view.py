"""
Home view - Main dashboard
"""
import customtkinter as ctk
from datetime import datetime
from src.utils import open_path


class HomeView(ctk.CTkFrame):
    """Home/Dashboard view"""

    def __init__(self, parent, app):
        """Initialize home view"""
        super().__init__(parent, corner_radius=0)
        self.app = app

        # Create layout
        self._create_layout()

    def _create_layout(self):
        """Create the home view layout"""
        # Main container with padding
        container = ctk.CTkFrame(self)
        container.pack(fill="both", expand=True, padx=20, pady=20)

        # Welcome section
        welcome_frame = ctk.CTkFrame(container)
        welcome_frame.pack(fill="x", pady=(0, 20))

        # Welcome message
        welcome_label = ctk.CTkLabel(
            welcome_frame,
            text="Welcome to CoolBox!",
            font=ctk.CTkFont(size=28, weight="bold"),
        )
        welcome_label.pack(pady=20)

        # Date/time
        date_label = ctk.CTkLabel(
            welcome_frame,
            text=datetime.now().strftime("%A, %B %d, %Y"),
            font=ctk.CTkFont(size=16),
        )
        date_label.pack()

        # Quick actions grid
        actions_frame = ctk.CTkFrame(container)
        actions_frame.pack(fill="both", expand=True)

        # Configure grid
        for i in range(2):
            actions_frame.grid_columnconfigure(i, weight=1)

        # Quick action cards
        self._create_action_card(
            actions_frame,
            "🚀 Quick Start",
            "Get started with a new project",
            self._quick_start,
            0,
            0,
        )

        self._create_action_card(
            actions_frame,
            "📁 Recent Files",
            "Open your recent documents",
            self._show_recent,
            0,
            1,
        )

        self._create_action_card(
            actions_frame,
            "🛠️ Tools",
            "Access powerful utilities",
            lambda: self.app.switch_view("tools"),
            1,
            0,
        )

        self._create_action_card(
            actions_frame,
            "⚙️ Settings",
            "Configure your preferences",
            lambda: self.app.switch_view("settings"),
            1,
            1,
        )

        # Statistics section
        stats_frame = ctk.CTkFrame(container)
        stats_frame.pack(fill="x", pady=(20, 0))

        stats_label = ctk.CTkLabel(
            stats_frame,
            text="📊 Statistics",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        stats_label.pack(anchor="w", padx=20, pady=10)

        # Stats grid
        stats_grid = ctk.CTkFrame(stats_frame)
        stats_grid.pack(fill="x", padx=20, pady=10)

        self._create_stat_item(stats_grid, "Files Processed", "127", 0)
        self._create_stat_item(stats_grid, "Time Saved", "48 hrs", 1)
        self._create_stat_item(stats_grid, "Active Projects", "5", 2)
        self._create_stat_item(stats_grid, "Efficiency", "94%", 3)

    def _create_action_card(self, parent, title: str, description: str, command, row: int, col: int):
        """Create an action card"""
        card = ctk.CTkFrame(parent, height=150)
        card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

        # Title
        title_label = ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        title_label.pack(pady=(20, 10))

        # Description
        desc_label = ctk.CTkLabel(
            card,
            text=description,
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        desc_label.pack(pady=(0, 20))

        # Button
        button = ctk.CTkButton(
            card,
            text="Open",
            command=command,
            width=100,
        )
        button.pack()

    def _create_stat_item(self, parent, label: str, value: str, column: int):
        """Create a statistics item"""
        frame = ctk.CTkFrame(parent)
        frame.grid(row=0, column=column, padx=10, sticky="ew")
        parent.grid_columnconfigure(column, weight=1)

        # Value
        value_label = ctk.CTkLabel(
            frame,
            text=value,
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        value_label.pack(pady=(10, 5))

        # Label
        label_label = ctk.CTkLabel(
            frame,
            text=label,
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        label_label.pack(pady=(0, 10))

    def _quick_start(self):
        """Handle quick start action"""
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Starting new project...", "info")
        from tkinter import filedialog
        from pathlib import Path

        filename = filedialog.asksaveasfilename(
            title="Create New File",
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
            parent=self,
        )
        if filename:
            path = Path(filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")
            self.app.config.add_recent_file(filename)
            self.app.refresh_recent_files()
            if self.app.status_bar is not None:
                self.app.status_bar.set_message(f"Created {filename}", "success")
            open_path(str(path))

    def _show_recent(self):
        """Show recent files"""
        recent_files = self.app.config.get("recent_files", [])
        if not recent_files:
            if self.app.status_bar is not None:
                self.app.status_bar.set_message("No recent files", "warning")
            return

        if self.app.status_bar is not None:
            self.app.status_bar.set_message(
                f"Found {len(recent_files)} recent files", "info"
            )

        window = ctk.CTkToplevel(self)
        window.title("Recent Files")

        def open_file(path: str) -> None:
            """Open *path* using the default application."""
            open_path(path)

        for path in recent_files:
            ctk.CTkButton(
                window,
                text=path,
                anchor="w",
                command=lambda p=path: open_file(p),
            ).pack(fill="x", padx=10, pady=5)
