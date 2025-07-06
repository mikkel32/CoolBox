import customtkinter as ctk
from .base_mixin import UIHelperMixin


class BaseDialog(ctk.CTkToplevel, UIHelperMixin):
    """Base class for dialogs providing shared styling."""

    def __init__(self, app, *, title: str = "", geometry: str | None = None, resizable: tuple[bool, bool] = (False, False)):
        ctk.CTkToplevel.__init__(self, app.window)
        UIHelperMixin.__init__(self, app)
        if hasattr(app, "register_dialog"):
            app.register_dialog(self)
        if hasattr(app, "get_icon_photo"):
            try:
                icon_photo = app.get_icon_photo()
                if icon_photo is not None:
                    self.iconphoto(False, icon_photo)
            except Exception:
                pass
        if title:
            self.title(title)
        if geometry:
            self.geometry(geometry)
        self.resizable(*resizable)
        self.bind("<Escape>", lambda e: self.destroy())

    def center_window(self) -> None:  # type: ignore[override]
        UIHelperMixin.center_window(self)

    def refresh_theme(self) -> None:  # type: ignore[override]
        UIHelperMixin.refresh_theme(self)

    def destroy(self) -> None:  # type: ignore[override]
        if hasattr(self.app, "unregister_dialog"):
            self.app.unregister_dialog(self)
        super().destroy()
