import customtkinter as ctk
from .base_mixin import UIHelperMixin


class SplashScreen(ctk.CTkToplevel, UIHelperMixin):
    """Simple splash screen shown during startup."""

    def __init__(self, app, *, duration: int = 1500, on_close=None) -> None:
        ctk.CTkToplevel.__init__(self, app.window)
        UIHelperMixin.__init__(self, app)
        self.app = app
        self.on_close = on_close
        self.overrideredirect(True)
        self.geometry("400x250")
        self.lift()
        self.update_idletasks()
        self.center_window(self)

        title = ctk.CTkLabel(self, text="CoolBox", font=self.title_font)
        self._mark_font_role(title, "title")
        title.pack(expand=True)

        self.progress = ctk.CTkProgressBar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=self.padx, pady=(0, self.pady))
        self.progress.start()
        self.after(duration, self.close)

    def refresh_theme(self) -> None:  # type: ignore[override]
        super().refresh_theme()
        self.progress.configure(progress_color=self.accent)

    def close(self) -> None:
        self.progress.stop()
        self.destroy()
        if self.on_close:
            try:
                self.on_close()
            except Exception:
                pass
