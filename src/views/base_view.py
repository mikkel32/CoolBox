import customtkinter as ctk
from .base_mixin import UIHelperMixin


class BaseView(ctk.CTkFrame, UIHelperMixin):
    """Base class for application views providing consistent styling."""

    def __init__(self, parent, app):
        ctk.CTkFrame.__init__(self, parent, corner_radius=0)
        UIHelperMixin.__init__(self, app)

    def refresh_theme(self) -> None:  # type: ignore[override]
        UIHelperMixin.refresh_theme(self)
