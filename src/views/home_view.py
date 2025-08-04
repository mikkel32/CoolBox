"""
Home view - Main dashboard
"""
import customtkinter as ctk
from datetime import datetime
from src.utils import open_path
from .base_view import BaseView
from ..components.widgets import info_label


class HomeView(BaseView):
    """Home/Dashboard view"""

    def __init__(self, parent, app):
        """Initialize home view"""
        super().__init__(parent, app)

        # Create layout
        self._create_layout()

        # Apply current styling
        self.refresh_fonts()
        self.refresh_theme()

    def _create_layout(self):
        """Create the home view layout"""
        # Main container with padding
        container = self.create_container()

        # Welcome section
        welcome_frame = ctk.CTkFrame(container)
        welcome_frame.pack(fill="x", pady=(0, 20))

        # Welcome message
        self.add_title(welcome_frame, "Welcome to CoolBox!")

        # Date/time
        date_label = ctk.CTkLabel(
            welcome_frame,
            text=datetime.now().strftime("%A, %B %d, %Y"),
            font=self.font,
        )
        date_label.pack()

        # Quick actions grid
        actions_frame = ctk.CTkFrame(container)
        actions_frame.pack(fill="both", expand=True)

        # Configure grid
        for i in range(2):
            actions_frame.grid_columnconfigure(i, weight=1)

        # Quick action cards
        self._action_buttons: list[ctk.CTkButton] = []

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
        stats_frame = self.add_section(container, "📊 Statistics")

        stats_grid = ctk.CTkFrame(stats_frame)
        stats_grid.pack(fill="x", padx=20, pady=10)

        self._create_stat_item(stats_grid, "Files Processed", "127", 0)
        self._create_stat_item(stats_grid, "Time Saved", "48 hrs", 1)
        self._create_stat_item(stats_grid, "Active Projects", "5", 2)
        self._create_stat_item(stats_grid, "Efficiency", "94%", 3)

        # Console section for watchdog logs
        console_frame = self.add_section(container, "Console")
        self.console = ctk.CTkTextbox(console_frame, height=120, state="disabled")
        self.console.pack(fill="both", padx=20, pady=10)
        self.console.tag_config("INFO", foreground=self.accent)
        self.console.tag_config("WARNING", foreground="#F39C12")
        self.console.tag_config("ERROR", foreground="#E74C3C")
        self._log_index = 0
        self._watch_logs()
    def _create_action_card(self, parent, title: str, description: str, command, row: int, col: int):
        """Create an action card"""
        card = ctk.CTkFrame(parent, height=150)
        card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

        # Title
        title_label = ctk.CTkLabel(
            card,
            text=title,
            font=self.section_font,
        )
        title_label.pack(pady=(20, 10))

        # Description
        desc_label = info_label(card, description, font=self.font)
        desc_label.pack(pady=(0, 20))

        # Button
        button = ctk.CTkButton(
            card,
            text="Open",
            command=command,
            width=100,
            fg_color=self.accent,
            hover_color=self.accent,
        )
        button.pack()
        self.add_tooltip(button, f"Launch {title}")
        self._action_buttons.append(button)

    def _create_stat_item(self, parent, label: str, value: str, column: int):
        """Create a statistics item"""
        frame = ctk.CTkFrame(parent)
        frame.grid(row=0, column=column, padx=10, sticky="ew")
        parent.grid_columnconfigure(column, weight=1)

        value_lbl = self.grid_label(frame, value, 0, columnspan=1)
        value_lbl.configure(font=self.section_font)

        label_lbl = info_label(frame, label, font=self.font)
        label_lbl.grid(row=1, column=0, columnspan=1, sticky="w")

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

        from .recent_files_dialog import RecentFilesDialog

        RecentFilesDialog(self.app, recent_files)

    def refresh_theme(self) -> None:  # type: ignore[override]
        super().refresh_theme()
        for btn in self._action_buttons:
            btn.configure(fg_color=self.accent, hover_color=self.accent)
        if hasattr(self, "console"):
            self.console.tag_config("INFO", foreground=self.accent)

    def _flush_logs(self) -> None:
        """Append any new watchdog logs to the console."""
        logs = self.app.thread_manager.logs
        while self._log_index < len(logs):
            raw = logs[self._log_index]
            self._log_index += 1
            if ":" in raw:
                level, text = raw.split(":", 1)
            else:
                level, text = "INFO", raw
            self.console.configure(state="normal")
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.console.insert(
                "end",
                f"[{timestamp}] [{level.strip().upper()}] {text.strip()}\n",
                level.strip().upper(),
            )
            lines = int(self.console.index("end-1c").split(".")[0])
            if lines > 200:
                self.console.delete("1.0", f"{lines - 200}.0")
            self.console.configure(state="disabled")
            self.console.see("end")

    def _watch_logs(self) -> None:
        """Periodically refresh console with latest logs."""
        self._flush_logs()
        self.after(500, self._watch_logs)
