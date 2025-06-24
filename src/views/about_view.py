"""
About view - Application info
"""
import customtkinter as ctk
from ..components.widgets import info_label


class AboutView(ctk.CTkFrame):
    """About screen view"""

    def __init__(self, parent, app):
        """Initialize about view"""
        super().__init__(parent, corner_radius=0)
        self.app = app

        # Create layout
        self._create_layout()

    def _create_layout(self):
        """Create the about view layout"""
        container = ctk.CTkFrame(self)
        container.pack(fill="both", expand=True, padx=20, pady=20)

        title = ctk.CTkLabel(
            container,
            text="About CoolBox",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        title.pack(pady=(0, 20))

        info = info_label(
            container,
            "CoolBox - A Modern Desktop App\nVersion 1.0",
        )
        info.pack(anchor="w")

        credits = info_label(container, "Created by mikkel32")
        credits.pack(anchor="w", pady=(20, 0))
