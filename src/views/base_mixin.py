import customtkinter as ctk
from src.components.tooltip import Tooltip
from src.utils.ui import center_window


class UIHelperMixin:
    """Mixin providing common UI helpers for views and dialogs."""

    def __init__(self, app=None):
        self.app = app
        self._registered_widgets: list[object] = []
        # fonts and padding will be configured via update_scale()
        self.font = ctk.CTkFont()
        self.title_font = ctk.CTkFont(weight="bold")
        self.section_font = ctk.CTkFont(weight="bold")
        self.accent = "#1faaff"
        if app is not None:
            self.accent = app.theme.get_theme().get("accent_color", "#1faaff")
        self.update_scale()

    def update_scale(self) -> None:
        """Refresh cached padding and font sizes using current UI scale."""
        if self.app is not None:
            scale = float(self.app.config.get("ui_scale", 1.0))
            base = int(self.app.config.get("font_size", 14))
            family = self.app.config.get("font_family", "Arial")
        else:
            scale = 1.0
            base = 14
            family = "Arial"
        self.padx = int(20 * scale)
        self.pady = int(20 * scale)
        self.gpadx = int(5 * scale)
        self.gpady = int(5 * scale)
        self.font.configure(size=int(base * scale), family=family)
        self.title_font.configure(size=int((base + 10) * scale), family=family)
        self.section_font.configure(size=int((base + 4) * scale), family=family)
        self.scale = scale

    # ------------------------------------------------------------------ font utils
    def _mark_font_role(self, widget: ctk.CTkBaseClass, role: str) -> None:
        """Store *role* on *widget* so fonts can be refreshed later."""
        setattr(widget, "_font_role", role)

    def _apply_font(self, widget: ctk.CTkBaseClass) -> None:
        role = getattr(widget, "_font_role", "normal")
        font = self.font
        if role == "title":
            font = self.title_font
        elif role == "section":
            font = self.section_font
        try:
            widget.configure(font=font)
        except Exception:
            pass

    def apply_fonts(self, parent: ctk.CTkBaseClass | None = None) -> None:
        """Recursively apply fonts to *parent* and its children."""
        parent = parent or self
        if hasattr(parent, "configure"):
            self._apply_font(parent)
        for child in parent.winfo_children():
            self.apply_fonts(child)

    def register_widget(self, widget: object) -> None:
        """Track a custom widget for theme and scale updates."""
        if widget not in self._registered_widgets:
            self._registered_widgets.append(widget)

    def refresh_scale(self) -> None:
        """Update padding, fonts and child widgets for new UI scale."""
        self.update_scale()
        self.apply_fonts()
        for widget in list(self._registered_widgets):
            try:
                if hasattr(widget, "refresh_scale"):
                    widget.refresh_scale()
            except Exception:
                pass

    def create_container(self, parent=None):
        """Return a padded container frame."""
        parent = parent or self
        container = ctk.CTkFrame(parent)
        container.pack(fill="both", expand=True, padx=self.padx, pady=self.pady)
        return container

    def create_card(self, parent=None, **kwargs):
        """Return a CardFrame with standard padding."""
        from ..components.card_frame import CardFrame

        parent = parent or self
        card = CardFrame(parent, self.app, **kwargs)
        card.pack(fill="both", expand=True, padx=self.padx, pady=self.pady)
        if hasattr(self, "register_widget"):
            self.register_widget(card)
        return card

    def add_title(self, parent, text: str, *, use_pack: bool = True):
        """Return a title label and optionally pack it."""
        label = ctk.CTkLabel(parent, text=text, font=self.title_font)
        self._mark_font_role(label, "title")
        if use_pack:
            label.pack(pady=(0, self.pady))
        return label

    def add_section(self, parent, title: str):
        """Create a section frame with a heading."""
        section = ctk.CTkFrame(parent)
        section.pack(fill="x", pady=(0, self.pady))
        header = ctk.CTkLabel(
            section,
            text=title,
            font=self.section_font,
        )
        self._mark_font_role(header, "section")
        header.pack(anchor="w", padx=self.padx, pady=(self.padx // 2, self.padx // 2))
        return section

    def add_collapsible_section(
        self, parent, title: str, *, key: str | None = None, expanded: bool = True
    ) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
        """Create a section that can be collapsed/expanded."""
        if key is not None:
            expanded = self.app.config.get_section_state(key, expanded)
        from ..components.card_frame import CardFrame

        section = CardFrame(parent, self.app)
        section.pack(fill="x", pady=(0, self.pady))
        container = section.inner

        header = ctk.CTkFrame(container, fg_color="transparent")
        header.pack(fill="x")
        icon = ctk.CTkLabel(header, text="▼" if expanded else "▶", width=20)
        icon.pack(side="left")
        label = ctk.CTkLabel(header, text=title, font=self.section_font)
        self._mark_font_role(label, "section")
        label.pack(side="left", padx=5)

        content = ctk.CTkFrame(container)
        if expanded:
            content.pack(fill="x", padx=self.padx)

        def _toggle(_=None):
            nonlocal expanded
            expanded = not expanded
            icon.configure(text="▼" if expanded else "▶")
            if expanded:
                content.pack(fill="x", padx=self.padx)
            else:
                content.pack_forget()
            if key is not None:
                self.app.config.set_section_state(key, expanded)

        header.bind("<Button-1>", _toggle)
        label.bind("<Button-1>", _toggle)
        icon.bind("<Button-1>", _toggle)

        return section, content

    # ------------------------------------------------------------------ grid helpers
    def grid_entry(
        self,
        parent: ctk.CTkFrame,
        label: str,
        variable: ctk.StringVar | ctk.IntVar,
        row: int,
        **entry_kwargs,
    ) -> ctk.CTkEntry:
        """Create a labeled entry row on a grid layout."""
        lbl = ctk.CTkLabel(parent, text=label, font=self.font)
        self._mark_font_role(lbl, "normal")
        lbl.grid(row=row, column=0, sticky="w", padx=self.gpadx, pady=self.gpady)
        entry = ctk.CTkEntry(parent, textvariable=variable, **entry_kwargs)
        self._mark_font_role(entry, "normal")
        entry.grid(row=row, column=1, sticky="ew", padx=self.gpadx, pady=self.gpady)
        parent.grid_columnconfigure(1, weight=1)
        return entry

    def grid_switch(
        self,
        parent: ctk.CTkFrame,
        text: str,
        variable: ctk.BooleanVar,
        row: int,
    ) -> ctk.CTkSwitch:
        """Create a switch row in a grid layout."""
        switch = ctk.CTkSwitch(parent, text=text, variable=variable, font=self.font)
        self._mark_font_role(switch, "normal")
        switch.grid(row=row, column=0, columnspan=2, sticky="w", padx=self.gpadx, pady=self.gpady)
        return switch

    def grid_checkbox(
        self,
        parent: ctk.CTkFrame,
        text: str,
        variable: ctk.BooleanVar,
        row: int,
        columnspan: int = 2,
    ) -> ctk.CTkCheckBox:
        """Create a check box row in a grid layout."""
        cb = ctk.CTkCheckBox(parent, text=text, variable=variable, font=self.font)
        self._mark_font_role(cb, "normal")
        cb.grid(row=row, column=0, columnspan=columnspan, sticky="w", padx=self.gpadx, pady=self.gpady)
        return cb

    def grid_optionmenu(
        self,
        parent: ctk.CTkFrame,
        label: str,
        variable: ctk.StringVar,
        values: list[str],
        row: int,
        **menu_kwargs,
    ) -> ctk.CTkOptionMenu:
        """Create a labeled option menu row on a grid layout."""
        lbl = ctk.CTkLabel(parent, text=label, font=self.font)
        self._mark_font_role(lbl, "normal")
        lbl.grid(row=row, column=0, sticky="w", padx=self.gpadx, pady=self.gpady)
        menu = ctk.CTkOptionMenu(
            parent, variable=variable, values=values, **menu_kwargs
        )
        self._mark_font_role(menu, "normal")
        menu.grid(row=row, column=1, sticky="ew", padx=self.gpadx, pady=self.gpady)
        parent.grid_columnconfigure(1, weight=1)
        return menu

    def grid_button(
        self,
        parent: ctk.CTkFrame,
        text: str,
        command,
        row: int,
        column: int = 0,
        columnspan: int = 2,
        **btn_kwargs,
    ) -> ctk.CTkButton:
        """Create a button row in a grid layout."""
        btn = ctk.CTkButton(parent, text=text, command=command, font=self.font, **btn_kwargs)
        self._mark_font_role(btn, "normal")
        btn.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            sticky="ew",
            padx=self.gpadx,
            pady=self.gpady,
        )
        return btn

    def grid_label(
        self,
        parent: ctk.CTkFrame,
        text: str,
        row: int,
        column: int = 0,
        columnspan: int = 2,
    ) -> ctk.CTkLabel:
        """Create a label row in a grid layout."""
        lbl = ctk.CTkLabel(parent, text=text, font=self.font)
        self._mark_font_role(lbl, "normal")
        lbl.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            sticky="w",
            padx=self.gpadx,
            pady=self.gpady,
        )
        return lbl

    def grid_separator(
        self,
        parent: ctk.CTkFrame,
        row: int,
        column: int = 0,
        columnspan: int = 2,
    ) -> ctk.CTkFrame:
        """Insert a thin separator line across the grid."""
        sep = ctk.CTkFrame(parent, height=1, fg_color=("gray60", "gray30"))
        sep.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            sticky="ew",
            padx=self.gpadx,
            pady=self.gpady,
        )
        parent.grid_columnconfigure(column, weight=1)
        return sep

    def grid_slider(
        self,
        parent: ctk.CTkFrame,
        label: str,
        variable: ctk.DoubleVar | ctk.IntVar,
        row: int,
        from_: float,
        to: float,
        **slider_kwargs,
    ) -> tuple[ctk.CTkSlider, ctk.CTkLabel]:
        """Create a labeled slider row returning the slider and value label."""
        lbl = ctk.CTkLabel(parent, text=label, font=self.font)
        self._mark_font_role(lbl, "normal")
        lbl.grid(row=row, column=0, sticky="w", padx=self.gpadx, pady=self.gpady)
        slider = ctk.CTkSlider(
            parent, variable=variable, from_=from_, to=to, **slider_kwargs
        )
        self._mark_font_role(slider, "normal")
        slider.grid(row=row, column=1, sticky="ew", padx=self.gpadx, pady=self.gpady)
        value_lbl = ctk.CTkLabel(parent, text=str(int(variable.get())), font=self.font)
        self._mark_font_role(value_lbl, "normal")
        value_lbl.grid(row=row, column=2, padx=self.gpadx, pady=self.gpady)
        parent.grid_columnconfigure(1, weight=1)

        def _update(val: float) -> None:
            value_lbl.configure(text=str(int(float(val))))

        slider.configure(command=_update)
        return slider, value_lbl

    def grid_file_entry(
        self,
        parent: ctk.CTkFrame,
        label: str,
        variable: ctk.StringVar,
        row: int,
        command,
        button_text: str = "Browse",
        **entry_kwargs,
    ) -> tuple[ctk.CTkEntry, ctk.CTkButton]:
        """Create a labeled entry with a browse button."""
        lbl = ctk.CTkLabel(parent, text=label, font=self.font)
        self._mark_font_role(lbl, "normal")
        lbl.grid(row=row, column=0, sticky="w", padx=self.gpadx, pady=self.gpady)
        entry = ctk.CTkEntry(parent, textvariable=variable, **entry_kwargs)
        self._mark_font_role(entry, "normal")
        entry.grid(row=row, column=1, sticky="ew", padx=self.gpadx, pady=self.gpady)
        btn = ctk.CTkButton(parent, text=button_text, command=command, width=80)
        self._mark_font_role(btn, "normal")
        btn.grid(row=row, column=2, padx=self.gpadx, pady=self.gpady)
        parent.grid_columnconfigure(1, weight=1)
        return entry, btn

    def grid_textbox(
        self,
        parent: ctk.CTkFrame,
        label: str,
        row: int,
        height: int = 150,
    ) -> ctk.CTkTextbox:
        """Create a labeled textbox occupying a single row."""
        lbl = ctk.CTkLabel(parent, text=label, font=self.font)
        self._mark_font_role(lbl, "normal")
        lbl.grid(row=row, column=0, sticky="nw", padx=self.gpadx, pady=self.gpady)
        box = ctk.CTkTextbox(parent, height=height)
        self._mark_font_role(box, "normal")
        box.grid(row=row, column=1, columnspan=2, sticky="nsew", padx=self.gpadx, pady=self.gpady)
        parent.grid_rowconfigure(row, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        return box

    def grid_segmented(
        self,
        parent: ctk.CTkFrame,
        label: str,
        variable: ctk.StringVar | ctk.IntVar,
        values: list[str],
        row: int,
        **seg_kwargs,
    ) -> ctk.CTkSegmentedButton:
        """Create a labeled segmented button row on a grid."""
        lbl = ctk.CTkLabel(parent, text=label, font=self.font)
        self._mark_font_role(lbl, "normal")
        lbl.grid(row=row, column=0, sticky="w", padx=self.gpadx, pady=self.gpady)
        seg = ctk.CTkSegmentedButton(
            parent, values=values, variable=variable, **seg_kwargs
        )
        self._mark_font_role(seg, "normal")
        seg.grid(row=row, column=1, sticky="ew", padx=self.gpadx, pady=self.gpady)
        parent.grid_columnconfigure(1, weight=1)
        return seg

    def create_search_box(
        self,
        parent: ctk.CTkFrame,
        variable: ctk.StringVar,
        placeholder: str,
        callback,
    ) -> ctk.CTkEntry:
        """Return an entry configured for search filtering."""
        entry = ctk.CTkEntry(
            parent,
            textvariable=variable,
            placeholder_text=placeholder,
        )
        self._mark_font_role(entry, "normal")
        entry.bind("<KeyRelease>", lambda e: callback())
        entry.bind("<Escape>", lambda e: (variable.set(""), callback()))
        return entry

    def create_search_entry(
        self,
        parent: ctk.CTkFrame,
        variable: ctk.StringVar,
        callback,
        placeholder: str = "Search...",
    ):
        """Return a SearchEntry widget with a built-in button."""
        from ..components.search_entry import SearchEntry

        entry = SearchEntry(parent, self.app, variable, callback, placeholder=placeholder)
        return entry

    def create_scrollable_container(self) -> ctk.CTkScrollableFrame:
        """Return a scrollable frame with standard padding."""
        frame = ctk.CTkScrollableFrame(self)
        frame.pack(fill="both", expand=True, padx=self.padx, pady=self.pady)
        return frame

    def add_tooltip(self, widget: ctk.CTkBaseClass, text: str) -> Tooltip:
        """Attach a tooltip to *widget* and return it.

        Some customtkinter widgets like ``CTkSegmentedButton`` do not implement
        ``bind``. In that case we attach events to their internal buttons
        instead so the tooltip still appears on hover.
        """
        tip = Tooltip(self, text)
        try:
            widget.bind(
                "<Enter>",
                lambda e, w=widget, t=tip: self._show_tooltip(w, t),
            )
            widget.bind("<Leave>", lambda e, t=tip: t.hide())
        except (NotImplementedError, AttributeError):
            if isinstance(widget, ctk.CTkSegmentedButton):
                for btn in widget._buttons_dict.values():
                    btn.bind(
                        "<Enter>",
                        lambda e, w=widget, t=tip: self._show_tooltip(w, t),
                    )
                    btn.bind("<Leave>", lambda e, t=tip: t.hide())
        return tip

    def _show_tooltip(self, widget: ctk.CTkBaseClass, tooltip: Tooltip) -> None:
        x = widget.winfo_rootx() + widget.winfo_width() // 2
        y = widget.winfo_rooty() + widget.winfo_height() + 10
        tooltip.show(x, y)

    def center_window(self, window: ctk.CTkToplevel | None = None) -> None:
        """Center *window* or self if no window provided."""
        if window is None and isinstance(self, ctk.CTkToplevel):
            window = self
        if window is not None:
            center_window(window)

    def refresh_fonts(self) -> None:
        """Update fonts based on the current config."""
        self.update_scale()
        self.apply_fonts()

    def refresh_theme(self) -> None:
        """Refresh cached theme colors."""
        if self.app is None:
            return
        self.accent = self.app.theme.get_theme().get("accent_color", "#1faaff")
        self.apply_theme()
        for widget in list(self._registered_widgets):
            try:
                if hasattr(widget, "refresh_theme"):
                    widget.refresh_theme()
            except Exception:
                pass

    # ------------------------------------------------------------------ theme helpers
    def apply_theme(self, parent: ctk.CTkBaseClass | None = None) -> None:
        """Recursively apply accent colors to buttons and inputs."""
        parent = parent or self
        if isinstance(parent, ctk.CTkButton):
            parent.configure(fg_color=self.accent, hover_color=self.accent)
        elif isinstance(parent, ctk.CTkSegmentedButton):
            parent.configure(fg_color=self.accent, selected_color=self.accent)
        elif isinstance(parent, ctk.CTkOptionMenu):
            parent.configure(
                fg_color=self.accent,
                button_color=self.accent,
                button_hover_color=self.accent,
            )
        elif isinstance(parent, ctk.CTkSwitch):
            parent.configure(progress_color=self.accent, fg_color=self.accent)
        elif isinstance(parent, ctk.CTkCheckBox):
            parent.configure(border_color=self.accent, fg_color=self.accent)
        elif isinstance(parent, ctk.CTkRadioButton):
            parent.configure(border_color=self.accent, fg_color=self.accent)
        elif isinstance(parent, ctk.CTkSlider):
            parent.configure(progress_color=self.accent)
        elif isinstance(parent, ctk.CTkEntry):
            parent.configure(border_color=self.accent)
        elif isinstance(parent, ctk.CTkProgressBar):
            parent.configure(progress_color=self.accent)
        for child in parent.winfo_children():
            self.apply_theme(child)
