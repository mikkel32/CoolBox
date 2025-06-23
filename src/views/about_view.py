"""
About view - Application info
"""
import customtkinter as ctk


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

        info = ctk.CTkLabel(
            container,
            text="CoolBox - A Modern Desktop App\nVersion 1.0",
            font=ctk.CTkFont(size=14),
            justify="left",
        )
        info.pack(anchor="w")

        credits = ctk.CTkLabel(
            container,
            text="Created by mikkel32",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        credits.pack(anchor="w", pady=(20, 0))
