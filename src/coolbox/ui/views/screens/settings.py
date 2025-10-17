"""
Settings view - Application preferences
"""
import json
import tkinter as tk
from tkinter import messagebox, colorchooser
from typing import Any, Iterable, cast

import customtkinter as ctk

from coolbox.utils.system_utils import slugify
from ..base import BaseView


class SettingsView(BaseView):
    """Settings and preferences view"""

    def __init__(self, parent, app):
        """Initialize settings view"""
        super().__init__(parent, app)

        # Create scrollable frame
        self.scroll_frame = self.create_scrollable_container()

        # Title
        self.add_title(self.scroll_frame, "⚙️ Settings")

        self.search_var = ctk.StringVar()
        self.search_entry = self.create_search_box(
            self.scroll_frame,
            self.search_var,
            "Search settings...",
            self._filter_sections,
        )
        self.search_entry.pack(fill="x", padx=20, pady=(0, 10))
        self.add_tooltip(self.search_entry, "Filter settings by text")
        self.app.window.bind("<Control-f>", lambda e: self._focus_search())
        self._sections: list[tuple[ctk.CTkFrame, str]] = []

        # Create settings sections
        self._create_appearance_settings()
        self._create_general_settings()
        self._create_advanced_settings()

        # Save button
        save_btn = ctk.CTkButton(
            self.scroll_frame,
            text="💾 Save Settings",
            command=self._save_settings,
            width=200,
            height=40,
            font=self.font,
        )
        save_btn.pack(pady=20)
        self.add_tooltip(save_btn, "Save all configuration values")

        self.no_results = ctk.CTkLabel(
            self.scroll_frame, text="No settings found", font=self.font
        )
        self.no_results.pack_forget()

        # Apply current styling
        self.refresh_fonts()
        self.refresh_theme()

    def _create_appearance_settings(self):
        """Create appearance settings section"""
        section, body = self._create_section("🎨 Appearance")

        # Theme selection
        theme_frame = ctk.CTkFrame(body)
        theme_frame.pack(fill="x", padx=20, pady=10)
        theme_frame.grid_columnconfigure(1, weight=1)
        self.theme_var = ctk.StringVar(
            value=self.app.config.get("appearance_mode", ctk.get_appearance_mode()).title()
        )
        theme_seg = self.grid_segmented(
            theme_frame,
            "Theme:",
            self.theme_var,
            ["Light", "Dark", "System"],
            0,
            command=self._change_theme,
        )
        self.add_tooltip(theme_seg, "Preview appearance mode")

        # Color theme
        color_frame = ctk.CTkFrame(body)
        color_frame.pack(fill="x", padx=20, pady=10)
        color_frame.grid_columnconfigure(1, weight=1)
        self.color_var = ctk.StringVar(value=self.app.config.get("color_theme", "blue"))
        color_seg = self.grid_segmented(
            color_frame,
            "Color Theme:",
            self.color_var,
            ["blue", "green", "dark-blue"],
            0,
            command=self._change_color_theme,
        )
        self.add_tooltip(color_seg, "Preview color theme")

        self.accent_color_var = ctk.StringVar(
            value=self.app.config.get("theme", {}).get("accent_color", "#007acc")
        )
        self.accent_display = ctk.CTkLabel(
            color_frame,
            text=" ",
            width=20,
            fg_color=self.accent_color_var.get(),
        )
        self.accent_display.grid(row=1, column=0, sticky="w", padx=6, pady=(6, 0))

        # Custom accent color picker
        accent_btn = ctk.CTkButton(
            color_frame,
            text="Choose Accent",
            width=140,
            command=self._pick_accent_color,
        )
        accent_btn.grid(row=1, column=1, sticky="w", padx=10, pady=(6, 0))
        self.add_tooltip(accent_btn, "Pick a custom accent color")

        # Theme management buttons
        theme_btns = ctk.CTkFrame(body)
        theme_btns.pack(fill="x", padx=20, pady=10)

        import_btn = ctk.CTkButton(
            theme_btns,
            text="Import Theme",
            command=self._import_theme,
            width=120,
        )
        import_btn.pack(side="left", padx=5)
        self.add_tooltip(import_btn, "Load a theme from file")

        export_btn = ctk.CTkButton(
            theme_btns,
            text="Export Theme",
            command=self._export_theme,
            width=120,
        )
        export_btn.pack(side="left", padx=5)
        self.add_tooltip(export_btn, "Save current theme to file")

        reset_btn = ctk.CTkButton(
            theme_btns,
            text="Reset Theme",
            command=self._reset_theme,
            width=120,
        )
        reset_btn.pack(side="left", padx=5)
        self.add_tooltip(reset_btn, "Restore default theme")

        # Font size
        font_frame = ctk.CTkFrame(body)
        font_frame.pack(fill="x", padx=20, pady=10)
        self.font_size_var = ctk.IntVar(value=self.app.config.get("font_size", 14))
        font_slider, font_label = self.grid_slider(
            font_frame,
            "Font Size:",
            self.font_size_var,
            0,
            from_=10,
            to=20,
        )
        self.add_tooltip(font_slider, "Adjust UI font size")
        self._register_section(section, "appearance")

    def _create_general_settings(self):
        """Create general settings section"""
        section, body = self._create_section("⚙️ General")

        # Auto-save
        self.auto_save_var = ctk.BooleanVar(value=self.app.config.get("auto_save", True))
        auto_save_check = ctk.CTkCheckBox(
            body,
            text="Enable auto-save",
            variable=self.auto_save_var,
        )
        auto_save_check.pack(anchor="w", padx=20, pady=5)

        # Show toolbar
        self.show_toolbar_var = ctk.BooleanVar(value=self.app.config.get("show_toolbar", True))
        toolbar_check = ctk.CTkCheckBox(
            body,
            text="Show toolbar",
            variable=self.show_toolbar_var,
        )
        toolbar_check.pack(anchor="w", padx=20, pady=5)

        # Show status bar
        self.show_statusbar_var = ctk.BooleanVar(value=self.app.config.get("show_statusbar", True))
        statusbar_check = ctk.CTkCheckBox(
            body,
            text="Show status bar",
            variable=self.show_statusbar_var,
        )
        statusbar_check.pack(anchor="w", padx=20, pady=5)

        # Show menu bar
        self.show_menu_var = ctk.BooleanVar(value=self.app.config.get("show_menu", True))
        menu_check = ctk.CTkCheckBox(
            body,
            text="Show menu bar",
            variable=self.show_menu_var,
        )
        menu_check.pack(anchor="w", padx=20, pady=5)

        # Recent files limit
        recent_frame = ctk.CTkFrame(body)
        recent_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            recent_frame,
            text="Recent files limit:",
            width=150,
            anchor="w",
            font=self.font,
        ).pack(side="left")

        self.recent_limit_var = ctk.IntVar(value=self.app.config.get("max_recent_files", 10))
        recent_spinbox = ctk.CTkEntry(
            recent_frame,
            textvariable=self.recent_limit_var,
            width=60,
        )
        recent_spinbox.pack(side="left", padx=10)
        self._register_section(section, "general")

    def _create_advanced_settings(self):
        """Create advanced settings section"""
        section, body = self._create_section("🔧 Advanced")

        # Clear cache button
        clear_cache_btn = ctk.CTkButton(
            body,
            text="🗑️ Clear Cache",
            command=self._clear_cache,
            width=200,
        )
        clear_cache_btn.pack(pady=10)

        ttl_frame = ctk.CTkFrame(body)
        ttl_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            ttl_frame,
            text="Scan cache TTL (s):",
            width=150,
            anchor="w",
            font=self.font,
        ).pack(side="left")

        self.scan_ttl_var = ctk.IntVar(value=self.app.config.get("scan_cache_ttl", 300))
        ctk.CTkEntry(ttl_frame, textvariable=self.scan_ttl_var, width=80).pack(side="left", padx=10)

        concurrency_frame = ctk.CTkFrame(body)
        concurrency_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            concurrency_frame,
            text="Scan concurrency:",
            width=150,
            anchor="w",
            font=self.font,
        ).pack(side="left")

        self.scan_concurrency_var = ctk.IntVar(value=self.app.config.get("scan_concurrency", 100))
        ctk.CTkEntry(concurrency_frame, textvariable=self.scan_concurrency_var, width=80).pack(side="left", padx=10)

        timeout_frame = ctk.CTkFrame(body)
        timeout_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            timeout_frame,
            text="Scan timeout (s):",
            width=150,
            anchor="w",
            font=self.font,
        ).pack(side="left")

        self.scan_timeout_var = ctk.DoubleVar(value=self.app.config.get("scan_timeout", 0.5))
        ctk.CTkEntry(timeout_frame, textvariable=self.scan_timeout_var, width=80).pack(side="left", padx=10)

        family_frame = ctk.CTkFrame(body)
        family_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            family_frame,
            text="Address family:",
            width=150,
            anchor="w",
            font=self.font,
        ).pack(side="left")

        self.scan_family_var = ctk.StringVar(value=self.app.config.get("scan_family", "auto"))
        ctk.CTkOptionMenu(
            family_frame,
            variable=self.scan_family_var,
            values=["auto", "ipv4", "ipv6"],
        ).pack(side="left", padx=10)

        self.scan_services_var = ctk.BooleanVar(value=self.app.config.get("scan_services", False))
        ctk.CTkCheckBox(
            body,
            text="Show service names",
            variable=self.scan_services_var,
        ).pack(anchor="w", padx=20, pady=5)

        self.scan_banner_var = ctk.BooleanVar(value=self.app.config.get("scan_banner", False))
        ctk.CTkCheckBox(
            body,
            text="Capture banners",
            variable=self.scan_banner_var,
        ).pack(anchor="w", padx=20, pady=5)

        self.scan_latency_var = ctk.BooleanVar(value=self.app.config.get("scan_latency", False))
        ctk.CTkCheckBox(
            body,
            text="Measure latency",
            variable=self.scan_latency_var,
        ).pack(anchor="w", padx=20, pady=5)

        self.scan_ping_var = ctk.BooleanVar(value=self.app.config.get("scan_ping", False))
        ctk.CTkCheckBox(
            body,
            text="Ping hosts before scanning",
            variable=self.scan_ping_var,
        ).pack(anchor="w", padx=20, pady=5)

        ping_opts = ctk.CTkFrame(body)
        ping_opts.pack(anchor="w", padx=20, pady=5)
        ctk.CTkLabel(ping_opts, text="Ping timeout:", font=self.font).pack(side="left")
        self.scan_ping_timeout_var = ctk.StringVar(value=str(self.app.config.get("scan_ping_timeout", 1.0)))
        ctk.CTkEntry(ping_opts, textvariable=self.scan_ping_timeout_var, width=60).pack(side="left", padx=(5, 15))
        ctk.CTkLabel(ping_opts, text="Ping concurrency:", font=self.font).pack(side="left")
        self.scan_ping_conc_var = ctk.StringVar(value=str(self.app.config.get("scan_ping_concurrency", 100)))
        ctk.CTkEntry(ping_opts, textvariable=self.scan_ping_conc_var, width=60).pack(side="left", padx=(5, 0))

        clear_scan_cache_btn = ctk.CTkButton(
            body,
            text="🗑️ Clear Scan Cache",
            command=self._clear_scan_cache,
            width=200,
        )
        clear_scan_cache_btn.pack(pady=10)

        clear_host_cache_btn = ctk.CTkButton(
            body,
            text="🗑️ Clear Host Cache",
            command=self._clear_host_cache,
            width=200,
        )
        clear_host_cache_btn.pack(pady=10)

        open_cache_btn = ctk.CTkButton(
            body,
            text="📂 Open Cache Folder",
            command=self._open_cache_folder,
            width=200,
        )
        open_cache_btn.pack(pady=10)

        open_config_btn = ctk.CTkButton(
            body,
            text="📂 Open Config Folder",
            command=self._open_config_folder,
            width=200,
        )
        open_config_btn.pack(pady=10)

        open_config_file_btn = ctk.CTkButton(
            body,
            text="📄 Open Config File",
            command=self._open_config_file_external,
            width=200,
        )
        open_config_file_btn.pack(pady=10)

        edit_config_btn = ctk.CTkButton(
            body,
            text="📝 Edit Config File",
            command=self._edit_config_file,
            width=200,
        )
        edit_config_btn.pack(pady=10)

        # Reset settings button
        reset_btn = ctk.CTkButton(
            body,
            text="🔄 Reset to Defaults",
            command=self._reset_settings,
            width=200,
            fg_color="red",
            hover_color="darkred",
        )
        reset_btn.pack(pady=10)

        # Export settings
        export_btn = ctk.CTkButton(
            body,
            text="📤 Export Settings",
            command=self._export_settings,
            width=200,
        )
        export_btn.pack(pady=10)

        # Import settings
        import_btn = ctk.CTkButton(
            body,
            text="📥 Import Settings",
            command=self._import_settings,
            width=200,
        )
        import_btn.pack(pady=10)
        self._register_section(section, "advanced")

    def _create_section(self, title: str) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
        """Create a collapsible settings section."""
        key = f"settings_{slugify(title)}"
        return self.add_collapsible_section(self.scroll_frame, title, key=key)

    def _change_theme(self, value):
        """Change application theme"""
        ctk.set_appearance_mode(value.lower())
        if self.app.status_bar is not None:
            self.app.status_bar.set_message(f"Theme changed to {value}", "info")

    def _change_color_theme(self, value):
        """Change color theme"""
        ctk.set_default_color_theme(value)
        if self.app.status_bar is not None:
            self.app.status_bar.set_message(f"Color theme changed to {value}", "info")
        messagebox.showinfo("Color Theme", "Please restart the application for changes to take effect")

    def _save_settings(self):
        """Save all settings"""
        # Update config
        self.app.config.set("appearance_mode", self.theme_var.get().lower())
        self.app.config.set("color_theme", self.color_var.get())
        self.app.config.set("font_size", self.font_size_var.get())
        self.app.config.set("auto_save", self.auto_save_var.get())
        self.app.config.set("show_toolbar", self.show_toolbar_var.get())
        self.app.config.set("show_statusbar", self.show_statusbar_var.get())
        self.app.config.set("show_menu", self.show_menu_var.get())
        self.app.config.set("max_recent_files", self.recent_limit_var.get())
        self.app.config.set("scan_cache_ttl", int(self.scan_ttl_var.get()))
        self.app.config.set("scan_concurrency", int(self.scan_concurrency_var.get()))
        self.app.config.set("scan_timeout", float(self.scan_timeout_var.get()))
        self.app.config.set("scan_family", self.scan_family_var.get())
        self.app.config.set("scan_services", self.scan_services_var.get())
        self.app.config.set("scan_banner", self.scan_banner_var.get())
        self.app.config.set("scan_latency", self.scan_latency_var.get())
        self.app.config.set("scan_ping", self.scan_ping_var.get())
        self.app.config.set("scan_ping_timeout", float(self.scan_ping_timeout_var.get()))
        self.app.config.set("scan_ping_concurrency", int(self.scan_ping_conc_var.get()))

        theme = self.app.theme.get_theme()
        theme["accent_color"] = self.accent_color_var.get()
        self.app.theme.apply_theme(theme)

        # Save to file
        self.app.config.save()
        self.app.update_fonts()
        self.app.update_theme()

        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Settings saved successfully!", "success")
        # Update visibility of optional UI elements
        self.app.update_ui_visibility()

    def _clear_cache(self):
        """Clear application cache"""
        if messagebox.askyesno("Clear Cache", "Are you sure you want to clear the cache?"):
            removed = self.app.config.clear_cache()
            from coolbox.utils import clear_scan_cache
            clear_scan_cache()
            if self.app.status_bar is not None:
                self.app.status_bar.set_message(
                    f"Cache cleared ({removed} items)", "success"
                )

    def _reset_settings(self):
        """Reset settings to defaults"""
        if messagebox.askyesno("Reset Settings", "Are you sure you want to reset all settings to defaults?"):
            self.app.config.reset_to_defaults()
            self.app.theme.apply_theme(self.app.config.get("theme", {}))
            self.app.update_fonts()
            self.app.update_theme()
            if self.app.status_bar is not None:
                self.app.status_bar.set_message("Settings reset to defaults!", "success")
            self.app.switch_view("settings")
            self.app.update_ui_visibility()
            self.show_menu_var.set(self.app.config.get("show_menu", True))
            self.scan_ttl_var.set(self.app.config.get("scan_cache_ttl", 300))
            self.scan_concurrency_var.set(self.app.config.get("scan_concurrency", 100))
            self.scan_timeout_var.set(self.app.config.get("scan_timeout", 0.5))
            self.scan_family_var.set(self.app.config.get("scan_family", "auto"))
            self.scan_services_var.set(self.app.config.get("scan_services", False))
            self.scan_banner_var.set(self.app.config.get("scan_banner", False))
            self.scan_latency_var.set(self.app.config.get("scan_latency", False))
            self.scan_ping_var.set(self.app.config.get("scan_ping", False))
            self.scan_ping_timeout_var.set(self.app.config.get("scan_ping_timeout", 1.0))
            self.scan_ping_conc_var.set(self.app.config.get("scan_ping_concurrency", 100))

    def _clear_scan_cache(self) -> None:
        """Clear cached port scan results."""
        from coolbox.utils import clear_scan_cache

        clear_scan_cache()
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Port scan cache cleared", "success")

    def _clear_host_cache(self) -> None:
        """Clear cached host resolution results."""
        from coolbox.utils import clear_host_cache

        clear_host_cache()
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Host cache cleared", "success")

    def _open_cache_folder(self) -> None:
        """Open the cache directory in the system file manager."""
        from coolbox.utils.system_utils import open_path

        open_path(str(self.app.config.cache_dir))

    def _open_config_folder(self) -> None:
        """Open the configuration directory in the system file manager."""
        from coolbox.utils.system_utils import open_path

        open_path(str(self.app.config.config_dir))

    def _open_config_file_external(self) -> None:
        """Open the configuration file using the system default editor."""
        from coolbox.utils.system_utils import open_path

        open_path(str(self.app.config.config_file))

    def _edit_config_file(self) -> None:
        """Edit the configuration file inside CoolBox."""
        window = ctk.CTkToplevel(self)
        window.title("Edit Config File")

        textbox = ctk.CTkTextbox(window, width=600, height=400)
        textbox.pack(fill="both", expand=True, padx=10, pady=10)

        try:
            data = self.app.config.config_file.read_text()
        except Exception:
            data = json.dumps(self.app.config.config, indent=4)
        textbox.insert("1.0", data)

        def save() -> None:
            text = textbox.get("1.0", "end-1c")
            try:
                new_cfg = json.loads(text)
            except Exception as exc:
                messagebox.showerror("Save Error", str(exc))
                return
            self.app.config.config = new_cfg
            self.app.config.save()
            messagebox.showinfo("Config", "Configuration saved")
            window.destroy()

        btn_frame = ctk.CTkFrame(window, fg_color="transparent")
        btn_frame.pack(pady=5)
        ctk.CTkButton(btn_frame, text="Save", command=save, width=100).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Cancel", command=window.destroy, width=100).pack(side="left", padx=5)
        self.center_window(window)

    def _export_settings(self):
        """Export settings to file"""
        from tkinter import filedialog

        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
        )
        if filename:
            import json

            with open(filename, "w") as f:
                json.dump(self.app.config.config, f, indent=4)
            if self.app.status_bar is not None:
                self.app.status_bar.set_message(f"Settings exported to {filename}", "success")

    def _import_settings(self):
        """Import settings from file"""
        from tkinter import filedialog

        filename = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if filename:
            try:
                import json

                with open(filename, "r") as f:
                    imported = json.load(f)
                    self.app.config.config.update(imported)
                    self.app.config.save()
                if self.app.status_bar is not None:
                    self.app.status_bar.set_message("Settings imported successfully!", "success")
                messagebox.showinfo("Import Complete", "Please restart the application for changes to take effect")
            except Exception as e:
                messagebox.showerror("Import Error", f"Failed to import settings: {str(e)}")

    def _pick_accent_color(self):
        """Prompt for a custom accent color."""
        color_code = colorchooser.askcolor(color=self.accent_color_var.get())[1]
        if color_code:
            self.accent_color_var.set(color_code)
            self.accent_display.configure(fg_color=color_code)
            theme = self.app.theme.get_theme()
            theme["accent_color"] = color_code
            self.app.theme.apply_theme(theme)

    def _export_theme(self) -> None:
        """Export the current theme to a JSON file."""
        from tkinter import filedialog

        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
        )
        if filename:
            self.app.theme.export_theme(filename)
            if self.app.status_bar is not None:
                self.app.status_bar.set_message(
                    f"Theme exported to {filename}", "success"
                )

    def _import_theme(self) -> None:
        """Import a custom theme from a JSON file."""
        from tkinter import filedialog

        filename = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if filename:
            try:
                self.app.theme.import_theme(filename)
                if self.app.status_bar is not None:
                    self.app.status_bar.set_message(
                        f"Theme imported from {filename}", "success"
                    )
            except Exception as exc:
                messagebox.showerror("Import Theme", str(exc))

    def _reset_theme(self) -> None:
        """Reset theme colors to defaults."""
        self.app.theme.use_default_theme()
        theme = self.app.theme.get_theme()
        self.accent_color_var.set(theme.get("accent_color", "#007acc"))
        self.accent_display.configure(fg_color=self.accent_color_var.get())
        self.app.update_theme()
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Theme reset to defaults", "success")

    # ------------------------------------------------------------------ search

    def _register_section(self, frame: ctk.CTkFrame, title: str) -> None:
        texts = " ".join(self._gather_texts(frame))
        self._sections.append((frame, f"{title} {texts}".lower()))

    def _gather_texts(self, widget: ctk.CTkBaseClass | tk.Widget) -> list[str]:
        parts: list[str] = []
        if hasattr(widget, "cget"):
            keys = getattr(widget, "keys", None)
            available: list[str] | None = None
            if callable(keys):
                try:
                    available = [
                        str(item) for item in cast(Iterable[Any], keys())
                    ]
                except Exception:
                    available = None
            if available and "text" in available:
                try:
                    txt = widget.cget("text")  # type: ignore[call-arg]
                except Exception:
                    txt = None
                if txt:
                    parts.append(str(txt))
        for child in widget.winfo_children():
            parts.extend(self._gather_texts(child))
        return parts

    def _filter_sections(self) -> None:
        query = self.search_var.get().lower()
        accent = self.app.theme.get_theme().get("accent_color", "#1faaff")
        for frame, text in self._sections:
            heading = frame.winfo_children()[0] if frame.winfo_children() else None
            match = query and query in text
            if match:
                if not frame.winfo_viewable():
                    frame.pack(fill="x", pady=(0, self.pady))
                if isinstance(heading, ctk.CTkLabel):
                    heading.configure(text_color=accent)
            else:
                if isinstance(heading, ctk.CTkLabel):
                    heading.configure(text_color=None)
                if frame.winfo_viewable() and query:
                    frame.pack_forget()
                elif not frame.winfo_viewable() and not query:
                    frame.pack(fill="x", pady=(0, self.pady))

        visible = any(f.winfo_viewable() for f, _ in self._sections)
        if visible:
            if self.no_results.winfo_ismapped():
                self.no_results.pack_forget()
        else:
            self.no_results.pack(pady=20)

    def _focus_search(self) -> None:
        """Focus the settings search box when active."""
        if self.app.current_view == "settings":
            self.search_entry.focus_set()

    def refresh_theme(self) -> None:  # type: ignore[override]
        super().refresh_theme()
        self.accent_display.configure(fg_color=self.accent)
