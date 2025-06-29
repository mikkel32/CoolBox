"""Quick settings dialog."""
from tkinter import colorchooser
from pathlib import Path
import json
import customtkinter as ctk

from .base_dialog import BaseDialog


class QuickSettingsDialog(BaseDialog):
    """Simple dialog for toggling common options."""

    def __init__(self, app):
        super().__init__(app, title="Quick Settings", geometry="300x300")
        self.original_scale = app.config.get("ui_scale", 1.0)
        self.applied = False
        self.original_font_size = app.config.get("font_size", 14)
        self.original_family = app.config.get("font_family", "Arial")
        self.original_appearance = app.config.get("appearance_mode", "dark")
        self.original_color_theme = app.config.get("color_theme", "blue")
        self.original_system_accent = app.config.get("use_system_accent", False)
        self.original_animations = app.config.get("enable_animations", True)
        self.original_theme = app.theme.get_theme()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        # Wrap the options inside a card for a cleaner modern look
        container = self.create_card(self, shadow=True)
        inner = container.inner

        self.add_title(inner, "Quick Settings", use_pack=False).grid(
            row=0, column=0, columnspan=2, pady=(0, self.pady)
        )

        self.menu_var = ctk.BooleanVar(value=app.config.get("show_menu", True))
        self.toolbar_var = ctk.BooleanVar(value=app.config.get("show_toolbar", True))
        self.status_var = ctk.BooleanVar(value=app.config.get("show_statusbar", True))
        self.splash_var = ctk.BooleanVar(value=app.config.get("show_splash", True))
        self.animations_var = ctk.BooleanVar(value=app.config.get("enable_animations", True))
        self.theme_var = ctk.StringVar(value=app.config.get("appearance_mode", "dark").title())
        self.color_var = ctk.StringVar(value=app.config.get("color_theme", "blue"))
        self.accent_var = ctk.StringVar(
            value=app.theme.get_theme().get("accent_color", "#007acc")
        )
        self.accent_var.trace_add("write", lambda *_: self._update_accent_preview())
        self.system_accent_var = ctk.BooleanVar(value=app.config.get("use_system_accent", False))
        self.font_size_var = ctk.IntVar(value=app.config.get("font_size", 14))
        self.ui_scale_var = ctk.DoubleVar(value=app.config.get("ui_scale", 1.0))
        self.font_family_var = ctk.StringVar(value=app.config.get("font_family", "Arial"))

        sw_menu = self.grid_switch(inner, "Show Menu Bar", self.menu_var, 1)
        self.add_tooltip(sw_menu, "Toggle the main menu")
        sw_toolbar = self.grid_switch(inner, "Show Toolbar", self.toolbar_var, 2)
        self.add_tooltip(sw_toolbar, "Toggle the toolbar")
        sw_status = self.grid_switch(inner, "Show Status Bar", self.status_var, 3)
        self.add_tooltip(sw_status, "Toggle the status bar")
        sw_splash = self.grid_switch(inner, "Show Splash Screen", self.splash_var, 4)
        self.add_tooltip(sw_splash, "Show splash screen on startup")
        sw_anim = self.grid_switch(inner, "Enable Animations", self.animations_var, 5)
        self.add_tooltip(sw_anim, "Slide views when switching")
        self.grid_separator(inner, 6)

        theme_seg = self.grid_segmented(
            inner,
            "Appearance:",
            self.theme_var,
            ["Light", "Dark", "System"],
            7,
            command=self._change_theme,
        )
        self.add_tooltip(theme_seg, "Preview appearance mode")
        color_seg = self.grid_segmented(
            inner,
            "Color Theme:",
            self.color_var,
            ["blue", "green", "dark-blue", "modern", "neon", "glass"],
            8,
            command=self._change_color_theme,
        )
        self.add_tooltip(color_seg, "Preview color theme")

        accent_btn = self.grid_button(
            inner,
            "Accent Color...",
            self._choose_accent,
            9,
            columnspan=1,
        )
        self.accent_display = ctk.CTkLabel(inner, textvariable=self.accent_var)
        self._mark_font_role(self.accent_display, "normal")
        self.accent_display.grid(row=9, column=1, sticky="w", padx=self.gpadx, pady=self.gpady)
        self.add_tooltip(accent_btn, "Select custom accent color")

        use_system = self.grid_checkbox(inner, "Use System Accent", self.system_accent_var, 10)
        self.add_tooltip(use_system, "Match accent color with your OS")
        self.system_accent_var.trace_add("write", lambda *_: self._toggle_system_accent())

        family_menu = ctk.CTkOptionMenu(
            inner,
            variable=self.font_family_var,
            values=["Arial", "Helvetica", "Courier", "Times New Roman"],
            command=lambda _: self._preview_font_family(),
        )
        self._mark_font_role(family_menu, "normal")
        family_menu.grid(row=10, column=0, columnspan=2, sticky="ew", padx=self.gpadx, pady=self.gpady)
        self.add_tooltip(family_menu, "Choose interface font")

        slider, lbl = self.grid_slider(
            inner,
            "Font Size:",
            self.font_size_var,
            12,
            from_=10,
            to=20,
        )
        self.add_tooltip(slider, "Preview font size")
        self.sample_font = ctk.CTkFont(
            size=self.font_size_var.get(), family=self.font_family_var.get()
        )

        scale_slider, _ = self.grid_slider(
            inner,
            "UI Scale:",
            self.ui_scale_var,
            13,
            from_=0.8,
            to=1.6,
        )
        self.add_tooltip(scale_slider, "Preview interface scale")

        def _update_preview(val: float) -> None:
            size = int(float(val))
            self.sample_font.configure(size=size, family=self.font_family_var.get())
            for child in self.preview.winfo_children():
                if isinstance(child, (ctk.CTkButton, ctk.CTkEntry)):
                    child.configure(font=self.sample_font)
            self._preview_font_size(size)

        slider.configure(command=_update_preview)

        def _update_scale(val: float) -> None:
            scale = float(val)
            ctk.set_widget_scaling(scale)
            ctk.set_window_scaling(scale)
            self.app.config.set("ui_scale", scale)
            self.app.update_ui_scale()

        scale_slider.configure(command=_update_scale)

        self.preview = ctk.CTkFrame(inner)
        self.preview.grid(row=14, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.preview.grid_columnconfigure(1, weight=1)
        lbl_preview = self.grid_label(self.preview, "Preview:", 0, columnspan=2)
        lbl_preview.configure(font=self.section_font)
        from ..components.icon_button import IconButton

        self.sample_button = IconButton(
            self.preview,
            self.app,
            "★",
            text="Button",
            width=80,
        )
        self.sample_button.grid(row=1, column=0, padx=self.gpadx, pady=self.gpady)
        ctk.CTkEntry(self.preview, placeholder_text="Entry").grid(row=1, column=1, sticky="ew", padx=self.gpadx, pady=self.gpady)
        self._update_accent_preview()

        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.grid(row=15, column=0, columnspan=2, pady=10)
        btn_frame.grid_columnconfigure((0, 1, 2), weight=1)
        self.apply_btn = IconButton(btn_frame, self.app, "💾", text="Apply", command=self._apply, width=100)
        self.apply_btn.grid(row=0, column=0, padx=self.gpadx, pady=self.gpady)
        self.add_tooltip(self.apply_btn, "Save settings")
        self.reset_btn = IconButton(btn_frame, self.app, "↩", text="Reset", command=self._reset, width=100)
        self.reset_btn.grid(row=0, column=1, padx=self.gpadx, pady=self.gpady)
        self.add_tooltip(self.reset_btn, "Restore previous values")
        self.cancel_btn = IconButton(btn_frame, self.app, "✖", text="Cancel", command=self._cancel, width=100)
        self.cancel_btn.grid(row=0, column=2, padx=self.gpadx, pady=self.gpady)
        self.add_tooltip(self.cancel_btn, "Close without saving")
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_columnconfigure(1, weight=1)

        self.center_window()

        # Apply current styling
        self.refresh_fonts()
        self.refresh_theme()

    def refresh_fonts(self) -> None:  # type: ignore[override]
        super().refresh_fonts()
        for child in self.preview.winfo_children():
            if isinstance(child, (ctk.CTkButton, ctk.CTkEntry)):
                child.configure(font=self.sample_font)
        self.sample_font.configure(
            size=self.font_size_var.get(), family=self.font_family_var.get()
        )

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
        cfg.set("show_splash", self.splash_var.get())
        cfg.set("enable_animations", self.animations_var.get())
        cfg.set("appearance_mode", self.theme_var.get().lower())
        cfg.set("color_theme", self.color_var.get())
        theme_cfg = cfg.get("theme", {})
        theme_cfg["accent_color"] = self.accent_var.get()
        cfg.set("theme", theme_cfg)
        cfg.set("use_system_accent", self.system_accent_var.get())
        cfg.set("font_family", self.font_family_var.get())
        cfg.set("font_size", self.font_size_var.get())
        cfg.set("ui_scale", float(self.ui_scale_var.get()))
        cfg.save()

        ctk.set_appearance_mode(cfg.get("appearance_mode", "dark"))
        color = cfg.get("color_theme", "blue")
        if color in {"modern", "neon", "glass"}:
            theme_path = (
                Path(__file__).resolve().parents[1]
                / "assets"
                / "themes"
                / f"{color}.json"
            )
            ctk.set_default_color_theme(str(theme_path))
        else:
            ctk.set_default_color_theme(color)
        self.app.theme.apply_theme(cfg.get("theme", {}))
        self.app.update_ui_scale()
        self.app.update_ui_visibility()
        self.app.update_fonts()
        self.app.update_theme()
        self.applied = True
        self.destroy()

    def _reset(self) -> None:
        cfg = self.app.config
        self.menu_var.set(cfg.get("show_menu", True))
        self.toolbar_var.set(cfg.get("show_toolbar", True))
        self.status_var.set(cfg.get("show_statusbar", True))
        self.splash_var.set(cfg.get("show_splash", True))
        self.animations_var.set(cfg.get("enable_animations", True))
        self.theme_var.set(cfg.get("appearance_mode", "dark").title())
        self.color_var.set(cfg.get("color_theme", "blue"))
        self.accent_var.set(cfg.get("theme", {}).get("accent_color", "#007acc"))
        self.font_size_var.set(cfg.get("font_size", 14))
        self.font_family_var.set(cfg.get("font_family", "Arial"))
        self.ui_scale_var.set(cfg.get("ui_scale", 1.0))
        self.system_accent_var.set(cfg.get("use_system_accent", False))
        ctk.set_appearance_mode(cfg.get("appearance_mode", "dark"))
        color = cfg.get("color_theme", "blue")
        if color in {"modern", "neon", "glass"}:
            theme_path = (
                Path(__file__).resolve().parents[1]
                / "assets"
                / "themes"
                / f"{color}.json"
            )
            ctk.set_default_color_theme(str(theme_path))
        else:
            ctk.set_default_color_theme(color)
        self.app.theme.apply_theme(cfg.get("theme", {}))
        self.app.update_ui_scale()
        self.app.update_fonts()
        self.app.update_theme()
        self.refresh_fonts()
        self._update_accent_preview()
        self._preview_font_size(self.font_size_var.get())
        self._preview_font_family()

    def _cancel(self) -> None:
        self.app.config.set("ui_scale", self.original_scale)
        self.app.config.set("font_size", self.original_font_size)
        self.app.config.set("font_family", self.original_family)
        self.app.config.set("use_system_accent", self.original_system_accent)
        self.app.config.set("enable_animations", self.original_animations)
        ctk.set_appearance_mode(self.original_appearance)
        color = self.original_color_theme
        if color in {"modern", "neon", "glass"}:
            theme_path = (
                Path(__file__).resolve().parents[1]
                / "assets"
                / "themes"
                / f"{color}.json"
            )
            ctk.set_default_color_theme(str(theme_path))
        else:
            ctk.set_default_color_theme(color)
        self.app.theme.apply_theme(self.original_theme)
        self.app.update_ui_scale()
        self.app.update_fonts()
        self.app.update_theme()
        self.destroy()

    def destroy(self) -> None:  # type: ignore[override]
        if not getattr(self, "applied", False):
            self.app.config.set("ui_scale", self.original_scale)
            self.app.config.set("font_size", self.original_font_size)
            self.app.config.set("font_family", self.original_family)
            self.app.config.set("use_system_accent", self.original_system_accent)
            self.app.config.set("enable_animations", self.original_animations)
            ctk.set_appearance_mode(self.original_appearance)
            color = self.original_color_theme
            if color in {"modern", "neon", "glass"}:
                theme_path = (
                    Path(__file__).resolve().parents[1]
                    / "assets"
                    / "themes"
                    / f"{color}.json"
                )
                ctk.set_default_color_theme(str(theme_path))
            else:
                ctk.set_default_color_theme(color)
            self.app.theme.apply_theme(self.original_theme)
            self.app.update_ui_scale()
            self.app.update_fonts()
            self.app.update_theme()
        super().destroy()

    def _change_theme(self, value: str) -> None:
        """Preview the selected appearance mode immediately."""
        ctk.set_appearance_mode(value.lower())

    def _change_color_theme(self, value: str) -> None:
        """Preview the selected color theme immediately."""
        if value in {"modern", "neon", "glass"}:
            theme_path = (
                Path(__file__).resolve().parents[1]
                / "assets"
                / "themes"
                / f"{value}.json"
            )
            ctk.set_default_color_theme(str(theme_path))
            try:
                data = json.loads(Path(theme_path).read_text())
                accent = data.get("CTk", {}).get("color_scale", {}).get("accent_color")
                if accent:
                    self.accent_var.set(accent)
            except Exception:
                pass
        else:
            ctk.set_default_color_theme(value)
        # reapply accent color across the UI
        theme = self.app.theme.get_theme()
        theme["accent_color"] = self.accent_var.get()
        self.app.theme.apply_theme(theme)
        self.app.update_theme()

    def _choose_accent(self) -> None:
        """Open a color picker and update the accent preview."""
        color = colorchooser.askcolor(initialcolor=self.accent_var.get(), parent=self)
        if color and color[1]:
            self.accent_var.set(color[1])

    def _toggle_system_accent(self) -> None:
        if self.system_accent_var.get():
            from src.utils.theme import get_system_accent_color

            self.accent_var.set(get_system_accent_color())
        self._update_accent_preview()

    def _update_accent_preview(self) -> None:
        """Refresh sample widget colors using the selected accent."""
        color = self.accent_var.get()
        if hasattr(self, "sample_button"):
            self.sample_button.configure(fg_color=color, hover_color=color)
        if hasattr(self, "accent_display"):
            self.accent_display.configure(text=color)
        theme = self.app.theme.get_theme()
        theme["accent_color"] = color
        self.app.theme.apply_theme(theme)
        self.app.update_theme()

    def _preview_font_size(self, size: int) -> None:
        """Preview font size changes across the application."""
        self.app.config.set("font_size", size)
        self.app.update_fonts()

    def _preview_font_family(self) -> None:
        """Preview font family changes across the application."""
        family = self.font_family_var.get()
        self.sample_font.configure(family=family)
        self.app.config.set("font_family", family)
        self.app.update_fonts()
