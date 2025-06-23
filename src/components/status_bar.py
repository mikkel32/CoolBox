"""
Status bar component for displaying messages
"""
import customtkinter as ctk
from datetime import datetime


class StatusBar(ctk.CTkFrame):
    """Application status bar"""

    def __init__(self, parent):
        """Initialize status bar"""
        super().__init__(parent, height=30, corner_radius=0)

        # Prevent frame from shrinking
        self.pack_propagate(False)

        # Message label
        self.message_label = ctk.CTkLabel(
            self,
            text="Ready",
            anchor="w",
            font=ctk.CTkFont(size=12),
        )
        self.message_label.pack(side="left", padx=10)

        # Right side info
        right_frame = ctk.CTkFrame(self, fg_color="transparent")
        right_frame.pack(side="right", padx=10)

        # Time label
        self.time_label = ctk.CTkLabel(
            right_frame,
            text="",
            font=ctk.CTkFont(size=12),
        )
        self.time_label.pack(side="right", padx=10)

        # Progress bar (hidden by default)
        self.progress = ctk.CTkProgressBar(
            self,
            width=200,
            height=10,
        )

        # Update time
        self._update_time()

    def set_message(self, message: str, msg_type: str = "info"):
        """Set status message with type"""
        # Set color based on type
        colors = {
            "info": "#3B8ED0",
            "success": "#00A65A",
            "warning": "#F39C12",
            "error": "#E74C3C",
        }

        color = colors.get(msg_type, "#3B8ED0")
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
