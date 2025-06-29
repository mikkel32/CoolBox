import customtkinter as ctk
from .base_component import BaseComponent


class CardFrame(BaseComponent):
    """Modern card-style frame with optional inner padding and shadow."""

    def __init__(self, parent, app, *, padding: int = 10, shadow: bool = False, **kwargs):
        super().__init__(parent, app, **kwargs)
        self.padding = padding
        self.shadow = None
        if shadow:
            self.shadow = ctk.CTkFrame(parent, corner_radius=8, fg_color="#00000020")
            self.shadow.place(in_=self, relx=0, rely=0, x=2, y=2, relwidth=1, relheight=1)
        self.configure(corner_radius=8, border_width=1)
        self.inner = ctk.CTkFrame(self, fg_color="transparent")
        self.inner.pack(expand=True, fill="both", padx=padding, pady=padding)
        # ensure child widgets update along with the card
        if hasattr(self, "register_widget"):
            self.register_widget(self.inner)

    def add_widget(self, widget: ctk.CTkBaseClass) -> None:
        """Pack a widget inside the card's inner frame."""
        widget.pack(in_=self.inner, expand=True, fill="both")

    def refresh_theme(self) -> None:  # type: ignore[override]
        super().refresh_theme()
        if getattr(self, "app", None) is not None:
            self.configure(border_color=self.accent)
        if self.shadow is not None:
            self.shadow.configure(fg_color="#00000020")

    def destroy(self) -> None:  # type: ignore[override]
        if self.shadow is not None:
            try:
                self.shadow.destroy()
            except Exception:
                pass
        super().destroy()
