"""Quick settings dialog."""
from tkinter import colorchooser
import customtkinter as ctk

from ..base import BaseDialog


class QuickSettingsDialog(BaseDialog):
    """Simple dialog for toggling common options."""

    def __init__(self, app):
        super().__init__(app, title="Quick Settings", geometry="300x300")

        container = self.create_container()

        self.add_title(container, "Quick Settings", use_pack=False).grid(
            row=0, column=0, columnspan=2, pady=(0, self.pady)
        )

        self.menu_var = ctk.BooleanVar(value=app.config.get("show_menu", True))
        self.toolbar_var = ctk.BooleanVar(value=app.config.get("show_toolbar", True))
        self.status_var = ctk.BooleanVar(value=app.config.get("show_statusbar", True))
        self.basic_render_var = ctk.BooleanVar(value=app.config.get("basic_rendering", False))
        self.theme_var = ctk.StringVar(value=app.config.get("appearance_mode", "dark").title())
        self.color_var = ctk.StringVar(value=app.config.get("color_theme", "blue"))
        self.accent_var = ctk.StringVar(
            value=app.theme.get_theme().get("accent_color", "#007acc")
        )
        self.accent_var.trace_add("write", lambda *_: self._update_accent_preview())
        self.font_size_var = ctk.IntVar(value=app.config.get("font_size", 14))

        sw_menu = self.grid_switch(container, "Show Menu Bar", self.menu_var, 1)
        self.add_tooltip(sw_menu, "Toggle the main menu")
        sw_toolbar = self.grid_switch(container, "Show Toolbar", self.toolbar_var, 2)
        self.add_tooltip(sw_toolbar, "Toggle the toolbar")
        sw_status = self.grid_switch(container, "Show Status Bar", self.status_var, 3)
        self.add_tooltip(sw_status, "Toggle the status bar")
        sw_basic = self.grid_switch(
            container, "Basic Rendering", self.basic_render_var, 4
        )
        self.add_tooltip(sw_basic, "Disable compositing effects for compatibility")
        self.grid_separator(container, 5)

        theme_seg = self.grid_segmented(
            container,
            "Appearance:",
            self.theme_var,
            ["Light", "Dark", "System"],
            6,
            command=self._change_theme,
        )
        self.add_tooltip(theme_seg, "Preview appearance mode")
        color_seg = self.grid_segmented(
            container,
            "Color Theme:",
            self.color_var,
            ["blue", "green", "dark-blue"],
            7,
            command=self._change_color_theme,
        )
        self.add_tooltip(color_seg, "Preview color theme")

        accent_btn = self.grid_button(
            container,
            "Accent Color...",
            self._choose_accent,
            8,
            columnspan=1,
        )
        self.accent_display = ctk.CTkLabel(container, textvariable=self.accent_var)
        self._mark_font_role(self.accent_display, "normal")
        self.accent_display.grid(row=8, column=1, sticky="w", padx=self.gpadx, pady=self.gpady)
        self.add_tooltip(accent_btn, "Select custom accent color")

        slider, lbl = self.grid_slider(
            container,
            "Font Size:",
            self.font_size_var,
            9,
            from_=10,
            to=20,
        )
        self.add_tooltip(slider, "Preview font size")
        self.sample_font = ctk.CTkFont(size=self.font_size_var.get())

        def _update_preview(val: float) -> None:
            size = int(float(val))
            self.sample_font.configure(size=size)
            for child in self.preview.winfo_children():
                if isinstance(child, ctk.CTkButton) or isinstance(child, ctk.CTkEntry):
                    child.configure(font=self.sample_font)

        slider.configure(command=_update_preview)

        self.preview = ctk.CTkFrame(container)
        self.preview.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.preview.grid_columnconfigure(1, weight=1)
        lbl_preview = self.grid_label(self.preview, "Preview:", 0, columnspan=2)
        lbl_preview.configure(font=self.section_font)
        self.sample_button = ctk.CTkButton(self.preview, text="Button", fg_color=self.accent, hover_color=self.accent)
        self.sample_button.grid(row=1, column=0, padx=self.gpadx, pady=self.gpady)
        ctk.CTkEntry(self.preview, placeholder_text="Entry").grid(row=1, column=1, sticky="ew", padx=self.gpadx, pady=self.gpady)
        self._update_accent_preview()

        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.grid(row=11, column=0, columnspan=2, pady=10)
        btn_frame.grid_columnconfigure((0, 1, 2), weight=1)
        self.apply_btn = self.grid_button(btn_frame, "Apply", self._apply, 0, column=0, columnspan=1)
        self.add_tooltip(self.apply_btn, "Save settings")
        self.reset_btn = self.grid_button(btn_frame, "Reset", self._reset, 0, column=1, columnspan=1)
        self.add_tooltip(self.reset_btn, "Restore previous values")
        self.cancel_btn = self.grid_button(btn_frame, "Cancel", self.destroy, 0, column=2, columnspan=1)
        self.add_tooltip(self.cancel_btn, "Close without saving")
        container.grid_columnconfigure(0, weight=1)
        container.grid_columnconfigure(1, weight=1)

        self.center_window()

        # Apply current styling
        self.refresh_fonts()
        self.refresh_theme()

    def refresh_fonts(self) -> None:  # type: ignore[override]
        super().refresh_fonts()
        for child in self.preview.winfo_children():
            if isinstance(child, (ctk.CTkButton, ctk.CTkEntry)):
                child.configure(font=self.sample_font)
        self.sample_font.configure(size=self.font_size_var.get())

    def refresh_theme(self) -> None:  # type: ignore[override]
        super().refresh_theme()
        self.accent_var.set(self.accent)
        self._update_accent_preview()
        for btn in (
            self.sample_button,
            self.apply_btn,
            self.reset_btn,
            self.cancel_btn,
        ):
            btn.configure(fg_color=self.accent, hover_color=self.accent)

    def _apply(self) -> None:
        cfg = self.app.config
        cfg.set("show_menu", self.menu_var.get())
        cfg.set("show_toolbar", self.toolbar_var.get())
        cfg.set("show_statusbar", self.status_var.get())
        cfg.set("basic_rendering", self.basic_render_var.get())
        cfg.set("appearance_mode", self.theme_var.get().lower())
        cfg.set("color_theme", self.color_var.get())
        theme_cfg = cfg.get("theme", {})
        theme_cfg["accent_color"] = self.accent_var.get()
        cfg.set("theme", theme_cfg)
        cfg.set("font_size", self.font_size_var.get())
        cfg.save()

        ctk.set_appearance_mode(cfg.get("appearance_mode", "dark"))
        ctk.set_default_color_theme(cfg.get("color_theme", "blue"))
        self.app.theme.apply_theme(cfg.get("theme", {}))
        self.app.update_ui_visibility()
        self.app.update_fonts()
        self.app.update_theme()
        self.destroy()

    def _reset(self) -> None:
        cfg = self.app.config
        self.menu_var.set(cfg.get("show_menu", True))
        self.toolbar_var.set(cfg.get("show_toolbar", True))
        self.status_var.set(cfg.get("show_statusbar", True))
        self.basic_render_var.set(cfg.get("basic_rendering", False))
        self.theme_var.set(cfg.get("appearance_mode", "dark").title())
        self.color_var.set(cfg.get("color_theme", "blue"))
        self.accent_var.set(cfg.get("theme", {}).get("accent_color", "#007acc"))
        self.font_size_var.set(cfg.get("font_size", 14))
        ctk.set_appearance_mode(cfg.get("appearance_mode", "dark"))
        ctk.set_default_color_theme(cfg.get("color_theme", "blue"))
        self.app.theme.apply_theme(cfg.get("theme", {}))
        self.app.update_fonts()
        self.app.update_theme()
        self._update_accent_preview()

    def _change_theme(self, value: str) -> None:
        """Preview the selected appearance mode immediately."""
        ctk.set_appearance_mode(value.lower())

    def _change_color_theme(self, value: str) -> None:
        """Preview the selected color theme immediately."""
        ctk.set_default_color_theme(value)

    def _choose_accent(self) -> None:
        """Open a color picker and update the accent preview."""
        color = colorchooser.askcolor(initialcolor=self.accent_var.get(), parent=self)
        if color and color[1]:
            self.accent_var.set(color[1])

    def _update_accent_preview(self) -> None:
        """Refresh sample widget colors using the selected accent."""
        color = self.accent_var.get()
        if hasattr(self, "sample_button"):
            self.sample_button.configure(fg_color=color, hover_color=color)
        if hasattr(self, "accent_display"):
            self.accent_display.configure(text=color)
