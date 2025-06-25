"""Quick settings dialog."""
import customtkinter as ctk


class QuickSettingsDialog(ctk.CTkToplevel):
    """Simple dialog for toggling common options."""

    def __init__(self, app):
        super().__init__(app.window)
        self.app = app
        self.title("Quick Settings")
        self.resizable(False, False)
        self.geometry("300x300")

        ctk.CTkLabel(
            self,
            text="Quick Settings",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(pady=10)

        self.menu_var = ctk.BooleanVar(value=app.config.get("show_menu", True))
        self.toolbar_var = ctk.BooleanVar(value=app.config.get("show_toolbar", True))
        self.status_var = ctk.BooleanVar(value=app.config.get("show_statusbar", True))
        self.sidebar_var = ctk.BooleanVar(value=not app.config.get("sidebar_collapsed", False))
        self.theme_var = ctk.StringVar(value=app.config.get("appearance_mode", "dark").title())
        self.color_var = ctk.StringVar(value=app.config.get("color_theme", "blue"))

        ctk.CTkCheckBox(self, text="Show Menu Bar", variable=self.menu_var).pack(anchor="w", padx=20, pady=5)
        ctk.CTkCheckBox(self, text="Show Toolbar", variable=self.toolbar_var).pack(anchor="w", padx=20, pady=5)
        ctk.CTkCheckBox(self, text="Show Status Bar", variable=self.status_var).pack(anchor="w", padx=20, pady=5)
        ctk.CTkCheckBox(self, text="Show Sidebar", variable=self.sidebar_var).pack(anchor="w", padx=20, pady=5)

        ctk.CTkLabel(self, text="Appearance:").pack(anchor="w", padx=20, pady=(10, 0))
        ctk.CTkOptionMenu(
            self,
            values=["Light", "Dark", "System"],
            variable=self.theme_var,
            command=self._change_theme,
            width=120,
        ).pack(anchor="w", padx=20, pady=5)

        ctk.CTkLabel(self, text="Color Theme:").pack(anchor="w", padx=20, pady=(10, 0))
        ctk.CTkOptionMenu(
            self,
            values=["blue", "green", "dark-blue"],
            variable=self.color_var,
            command=self._change_color_theme,
            width=120,
        ).pack(anchor="w", padx=20, pady=5)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text="Apply", command=self._apply).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Cancel", command=self.destroy).pack(side="left", padx=10)

    def _apply(self) -> None:
        cfg = self.app.config
        cfg.set("show_menu", self.menu_var.get())
        cfg.set("show_toolbar", self.toolbar_var.get())
        cfg.set("show_statusbar", self.status_var.get())
        cfg.set("sidebar_collapsed", not self.sidebar_var.get())
        cfg.set("appearance_mode", self.theme_var.get().lower())
        cfg.set("color_theme", self.color_var.get())
        cfg.save()

        ctk.set_appearance_mode(cfg.get("appearance_mode", "dark"))
        ctk.set_default_color_theme(cfg.get("color_theme", "blue"))
        self.app.theme.apply_theme(cfg.get("theme", {}))
        self.app.sidebar.set_collapsed(cfg.get("sidebar_collapsed", False))
        self.app.update_ui_visibility()
        self.destroy()

    def _change_theme(self, value: str) -> None:
        """Preview the selected appearance mode immediately."""
        ctk.set_appearance_mode(value.lower())

    def _change_color_theme(self, value: str) -> None:
        """Preview the selected color theme immediately."""
        ctk.set_default_color_theme(value)
