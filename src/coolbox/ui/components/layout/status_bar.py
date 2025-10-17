"""
Status bar component for displaying messages
"""

import customtkinter as ctk
from datetime import datetime
from ..widgets import Tooltip


class StatusBar(ctk.CTkFrame):
    """Application status bar"""

    def __init__(self, parent, app):
        """Initialize status bar"""
        super().__init__(parent, height=30, corner_radius=0)
        self.app = app

        # Prevent frame from shrinking
        self.pack_propagate(False)

        size = int(app.config.get("font_size", 14))
        self.font = ctk.CTkFont(size=max(size - 2, 8))
        # Message label
        self.accent = app.theme.get_theme().get("accent_color", "#1faaff")
        self.message_label = ctk.CTkLabel(
            self,
            text="Ready",
            anchor="w",
            font=self.font,
        )
        self.message_label.pack(side="left", padx=10)

        # Right side info
        right_frame = ctk.CTkFrame(self, fg_color="transparent")
        right_frame.pack(side="right", padx=10)

        # Time label
        # Use a monospaced font and fixed width to avoid jitter when the
        # time text updates every second. Measure the width of the
        # "00:00:00" string so the label size adapts to the chosen font.
        self.time_font = ctk.CTkFont(size=max(size - 2, 8), family="Courier")
        try:
            width = self.time_font.measure("00:00:00")
        except Exception:  # pragma: no cover - measure may fail in headless env
            width = 70
        self.time_label = ctk.CTkLabel(
            right_frame,
            text="00:00:00",
            font=self.time_font,
            width=width,
        )
        self.time_label.pack(side="right", padx=10)

        self._time_tip = Tooltip(self, "")
        self.time_label.bind("<Enter>", lambda e: self._show_time())
        self.time_label.bind("<Leave>", lambda e: self._time_tip.hide())

        # Progress bar (hidden by default)
        self.progress = ctk.CTkProgressBar(
            self,
            width=200,
            height=10,
        )
        self.progress.configure(progress_color=self.accent)

        # Update time
        self.colors = {
            "info": self.accent,
            "success": "#00A65A",
            "warning": "#F39C12",
            "error": "#E74C3C",
        }
        self._update_time()

    def set_message(self, message: str, msg_type: str = "info"):
        """Set status message with type"""
        # Set color based on type
        color = self.colors.get(msg_type, self.accent)
        self.message_label.configure(text=message, text_color=color)

        # Auto-clear after 5 seconds for non-info messages
        if msg_type != "info":
            self.after(5000, lambda: self.set_message("Ready"))

    def show_progress(self, value: float = 0):
        """Show progress bar with value (0-1)"""
        self.progress.set(value)
        self.progress.pack(side="left", padx=20)

    def hide_progress(self):
        """Hide progress bar"""
        self.progress.pack_forget()

    def _update_time(self):
        """Update time display"""
        current_time = datetime.now().strftime("%H:%M:%S")
        self.time_label.configure(text=current_time)
        # Update every second
        self.after(1000, self._update_time)

    def _show_time(self) -> None:
        """Show tooltip with the current date under the clock."""
        date_text = datetime.now().strftime("%A, %B %d, %Y")
        self._time_tip.label.configure(text=date_text)
        x = self.time_label.winfo_rootx() + self.time_label.winfo_width() // 2
        y = self.time_label.winfo_rooty() + self.time_label.winfo_height() + 10
        self._time_tip.show(x, y)

    def refresh_fonts(self) -> None:
        """Refresh fonts using the application's font size."""
        size = int(self.app.config.get("font_size", 14))
        self.font.configure(size=max(size - 2, 8))
        self.time_font.configure(size=max(size - 2, 8))
        self.message_label.configure(font=self.font)
        self.time_label.configure(font=self.time_font)

    def refresh_theme(self) -> None:
        """Refresh accent color used for info messages."""
        self.accent = self.app.theme.get_theme().get("accent_color", "#1faaff")
        self.colors["info"] = self.accent
        self.progress.configure(progress_color=self.accent)
