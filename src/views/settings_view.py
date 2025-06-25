"""
Settings view - Application preferences
"""
import customtkinter as ctk
from tkinter import messagebox, colorchooser
import json


class SettingsView(ctk.CTkFrame):
    """Settings and preferences view"""

    def __init__(self, parent, app):
        """Initialize settings view"""
        super().__init__(parent, corner_radius=0)
        self.app = app

        # Create scrollable frame
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Title
        title = ctk.CTkLabel(
            self.scroll_frame,
            text="⚙️ Settings",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        title.pack(pady=(0, 20))

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
            font=ctk.CTkFont(size=14),
        )
        save_btn.pack(pady=20)

    def _create_appearance_settings(self):
        """Create appearance settings section"""
        section = self._create_section("🎨 Appearance")

        # Theme selection
        theme_frame = ctk.CTkFrame(section)
        theme_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            theme_frame,
            text="Theme:",
            width=150,
            anchor="w",
        ).pack(side="left")

        self.theme_var = ctk.StringVar(value=ctk.get_appearance_mode())
        theme_menu = ctk.CTkOptionMenu(
            theme_frame,
            values=["Light", "Dark", "System"],
            variable=self.theme_var,
            command=self._change_theme,
        )
        theme_menu.pack(side="left", padx=10)

        # Color theme
        color_frame = ctk.CTkFrame(section)
        color_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            color_frame,
            text="Color Theme:",
            width=150,
            anchor="w",
        ).pack(side="left")

        self.color_var = ctk.StringVar(value="blue")
        color_menu = ctk.CTkOptionMenu(
            color_frame,
            values=["blue", "green", "dark-blue"],
            variable=self.color_var,
            command=self._change_color_theme,
        )
        color_menu.pack(side="left", padx=10)

        self.accent_color_var = ctk.StringVar(
            value=self.app.config.get("theme", {}).get("accent_color", "#007acc")
        )
        self.accent_display = ctk.CTkLabel(
            color_frame, text=" ", width=20, fg_color=self.accent_color_var.get()
        )
        self.accent_display.pack(side="left", padx=6)

        # Custom accent color picker
        accent_btn = ctk.CTkButton(
            color_frame,
            text="Choose Accent",
            width=140,
            command=self._pick_accent_color,
        )
        accent_btn.pack(side="left", padx=10)

        # Theme management buttons
        theme_btns = ctk.CTkFrame(section)
        theme_btns.pack(fill="x", padx=20, pady=10)

        ctk.CTkButton(
            theme_btns,
            text="Import Theme",
            command=self._import_theme,
            width=120,
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            theme_btns,
            text="Export Theme",
            command=self._export_theme,
            width=120,
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            theme_btns,
            text="Reset Theme",
            command=self._reset_theme,
            width=120,
        ).pack(side="left", padx=5)

        # Font size
        font_frame = ctk.CTkFrame(section)
        font_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            font_frame,
            text="Font Size:",
            width=150,
            anchor="w",
        ).pack(side="left")

        self.font_size_var = ctk.IntVar(value=self.app.config.get("font_size", 14))
        font_slider = ctk.CTkSlider(
            font_frame,
            from_=10,
            to=20,
            variable=self.font_size_var,
            width=200,
        )
        font_slider.pack(side="left", padx=10)

        font_label = ctk.CTkLabel(font_frame, text=str(self.font_size_var.get()))
        font_label.pack(side="left", padx=10)

        # Update label when slider changes
        def update_font_label(value):
            font_label.configure(text=str(int(value)))

        font_slider.configure(command=update_font_label)

    def _create_general_settings(self):
        """Create general settings section"""
        section = self._create_section("⚙️ General")

        # Auto-save
        self.auto_save_var = ctk.BooleanVar(value=self.app.config.get("auto_save", True))
        auto_save_check = ctk.CTkCheckBox(
            section,
            text="Enable auto-save",
            variable=self.auto_save_var,
        )
        auto_save_check.pack(anchor="w", padx=20, pady=5)

        # Show toolbar
        self.show_toolbar_var = ctk.BooleanVar(value=self.app.config.get("show_toolbar", True))
        toolbar_check = ctk.CTkCheckBox(
            section,
            text="Show toolbar",
            variable=self.show_toolbar_var,
        )
        toolbar_check.pack(anchor="w", padx=20, pady=5)

        # Show status bar
        self.show_statusbar_var = ctk.BooleanVar(value=self.app.config.get("show_statusbar", True))
        statusbar_check = ctk.CTkCheckBox(
            section,
            text="Show status bar",
            variable=self.show_statusbar_var,
        )
        statusbar_check.pack(anchor="w", padx=20, pady=5)

        # Show menu bar
        self.show_menu_var = ctk.BooleanVar(value=self.app.config.get("show_menu", True))
        menu_check = ctk.CTkCheckBox(
            section,
            text="Show menu bar",
            variable=self.show_menu_var,
        )
        menu_check.pack(anchor="w", padx=20, pady=5)

        # Recent files limit
        recent_frame = ctk.CTkFrame(section)
        recent_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            recent_frame,
            text="Recent files limit:",
            width=150,
            anchor="w",
        ).pack(side="left")

        self.recent_limit_var = ctk.IntVar(value=self.app.config.get("max_recent_files", 10))
        recent_spinbox = ctk.CTkEntry(
            recent_frame,
            textvariable=self.recent_limit_var,
            width=60,
        )
        recent_spinbox.pack(side="left", padx=10)

    def _create_advanced_settings(self):
        """Create advanced settings section"""
        section = self._create_section("🔧 Advanced")

        # Clear cache button
        clear_cache_btn = ctk.CTkButton(
            section,
            text="🗑️ Clear Cache",
            command=self._clear_cache,
            width=200,
        )
        clear_cache_btn.pack(pady=10)

        ttl_frame = ctk.CTkFrame(section)
        ttl_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            ttl_frame,
            text="Scan cache TTL (s):",
            width=150,
            anchor="w",
        ).pack(side="left")

        self.scan_ttl_var = ctk.IntVar(value=self.app.config.get("scan_cache_ttl", 300))
        ctk.CTkEntry(ttl_frame, textvariable=self.scan_ttl_var, width=80).pack(side="left", padx=10)

        concurrency_frame = ctk.CTkFrame(section)
        concurrency_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            concurrency_frame,
            text="Scan concurrency:",
            width=150,
            anchor="w",
        ).pack(side="left")

        self.scan_concurrency_var = ctk.IntVar(value=self.app.config.get("scan_concurrency", 100))
        ctk.CTkEntry(concurrency_frame, textvariable=self.scan_concurrency_var, width=80).pack(side="left", padx=10)

        timeout_frame = ctk.CTkFrame(section)
        timeout_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            timeout_frame,
            text="Scan timeout (s):",
            width=150,
            anchor="w",
        ).pack(side="left")

        self.scan_timeout_var = ctk.DoubleVar(value=self.app.config.get("scan_timeout", 0.5))
        ctk.CTkEntry(timeout_frame, textvariable=self.scan_timeout_var, width=80).pack(side="left", padx=10)

        family_frame = ctk.CTkFrame(section)
        family_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            family_frame,
            text="Address family:",
            width=150,
            anchor="w",
        ).pack(side="left")

        self.scan_family_var = ctk.StringVar(value=self.app.config.get("scan_family", "auto"))
        ctk.CTkOptionMenu(
            family_frame,
            variable=self.scan_family_var,
            values=["auto", "ipv4", "ipv6"],
        ).pack(side="left", padx=10)

        clear_scan_cache_btn = ctk.CTkButton(
            section,
            text="🗑️ Clear Scan Cache",
            command=self._clear_scan_cache,
            width=200,
        )
        clear_scan_cache_btn.pack(pady=10)

        clear_host_cache_btn = ctk.CTkButton(
            section,
            text="🗑️ Clear Host Cache",
            command=self._clear_host_cache,
            width=200,
        )
        clear_host_cache_btn.pack(pady=10)

        open_cache_btn = ctk.CTkButton(
            section,
            text="📂 Open Cache Folder",
            command=self._open_cache_folder,
            width=200,
        )
        open_cache_btn.pack(pady=10)

        open_config_btn = ctk.CTkButton(
            section,
            text="📂 Open Config Folder",
            command=self._open_config_folder,
            width=200,
        )
        open_config_btn.pack(pady=10)

        open_config_file_btn = ctk.CTkButton(
            section,
            text="📄 Open Config File",
            command=self._open_config_file_external,
            width=200,
        )
        open_config_file_btn.pack(pady=10)

        edit_config_btn = ctk.CTkButton(
            section,
            text="📝 Edit Config File",
            command=self._edit_config_file,
            width=200,
        )
        edit_config_btn.pack(pady=10)

        # Reset settings button
        reset_btn = ctk.CTkButton(
            section,
            text="🔄 Reset to Defaults",
            command=self._reset_settings,
            width=200,
            fg_color="red",
            hover_color="darkred",
        )
        reset_btn.pack(pady=10)

        # Export settings
        export_btn = ctk.CTkButton(
            section,
            text="📤 Export Settings",
            command=self._export_settings,
            width=200,
        )
        export_btn.pack(pady=10)

        # Import settings
        import_btn = ctk.CTkButton(
            section,
            text="📥 Import Settings",
            command=self._import_settings,
            width=200,
        )
        import_btn.pack(pady=10)

    def _create_section(self, title: str) -> ctk.CTkFrame:
        """Create a settings section"""
        section = ctk.CTkFrame(self.scroll_frame)
        section.pack(fill="x", pady=(0, 20))

        # Section title
        title_label = ctk.CTkLabel(
            section,
            text=title,
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        title_label.pack(anchor="w", padx=20, pady=(15, 10))

        return section

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

        theme = self.app.theme.get_theme()
        theme["accent_color"] = self.accent_color_var.get()
        self.app.theme.apply_theme(theme)

        # Save to file
        self.app.config.save()

        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Settings saved successfully!", "success")
        # Update visibility of optional UI elements
        self.app.update_ui_visibility()

    def _clear_cache(self):
        """Clear application cache"""
        if messagebox.askyesno("Clear Cache", "Are you sure you want to clear the cache?"):
            removed = self.app.config.clear_cache()
            from src.utils import clear_scan_cache
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
            if self.app.status_bar is not None:
                self.app.status_bar.set_message("Settings reset to defaults!", "success")
            self.app.switch_view("settings")
            self.app.update_ui_visibility()
            self.show_menu_var.set(self.app.config.get("show_menu", True))
            self.scan_ttl_var.set(self.app.config.get("scan_cache_ttl", 300))
            self.scan_concurrency_var.set(self.app.config.get("scan_concurrency", 100))
            self.scan_timeout_var.set(self.app.config.get("scan_timeout", 0.5))
            self.scan_family_var.set(self.app.config.get("scan_family", "auto"))

    def _clear_scan_cache(self) -> None:
        """Clear cached port scan results."""
        from src.utils import clear_scan_cache

        clear_scan_cache()
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Port scan cache cleared", "success")

    def _clear_host_cache(self) -> None:
        """Clear cached host resolution results."""
        from src.utils import clear_host_cache

        clear_host_cache()
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Host cache cleared", "success")

    def _open_cache_folder(self) -> None:
        """Open the cache directory in the system file manager."""
        from src.utils import open_path

        open_path(str(self.app.config.cache_dir))

    def _open_config_folder(self) -> None:
        """Open the configuration directory in the system file manager."""
        from src.utils import open_path

        open_path(str(self.app.config.config_dir))

    def _open_config_file_external(self) -> None:
        """Open the configuration file using the system default editor."""
        from src.utils import open_path

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
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Theme reset to defaults", "success")
