"""
About view - Application info
"""
from ..components.widgets import info_label
from ..utils import open_path
from .base_view import BaseView


class AboutView(BaseView):
    """About screen view"""

    def __init__(self, parent, app):
        """Initialize about view"""
        super().__init__(parent, app)

        # Create layout
        self._create_layout()

        # Apply current styling
        self.refresh_fonts()
        self.refresh_theme()

    def _create_layout(self):
        """Create the about view layout"""
        container = self.create_container()

        self.add_title(container, "About CoolBox")

        info = info_label(
            container,
            "CoolBox - A Modern Desktop App\nVersion 1.0.57",
            font=self.font,
        )
        info.pack(anchor="w")

        credits = info_label(container, "Created by mikkel32", font=self.font)
        credits.pack(anchor="w", pady=(20, 0))
        self.add_tooltip(credits, "Visit the CoolBox repository")
        self.credits_label = credits
        credits.configure(cursor="hand2", text_color=self.accent)
        credits.bind("<Button-1>", lambda e: open_path("https://github.com/mikkel32/CoolBox"))

    def refresh_theme(self) -> None:  # type: ignore[override]
        super().refresh_theme()
        if hasattr(self, "credits_label"):
            self.credits_label.configure(text_color=self.accent)
