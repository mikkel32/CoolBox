import customtkinter as ctk
from ..views.base_mixin import UIHelperMixin


class BaseComponent(ctk.CTkFrame, UIHelperMixin):
    """Base frame for shared component styling and scaling."""

    def __init__(self, parent, app, **kwargs):
        ctk.CTkFrame.__init__(self, parent, **kwargs)
        UIHelperMixin.__init__(self, app)
        # Automatically register with parent so theme and scale updates
        # propagate without manual calls.
        if hasattr(parent, "register_widget"):
            try:
                parent.register_widget(self)
            except Exception:
                pass
