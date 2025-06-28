"""Dialog showing a list of recently opened files."""

import customtkinter as ctk

from pathlib import Path
from ..utils import open_path
from .base_dialog import BaseDialog


class RecentFilesDialog(BaseDialog):
    """Simple dialog listing recent files."""

    def __init__(self, app, files: list[str]):
        super().__init__(app, title="Recent Files", geometry="500x400")

        self.rows: list[tuple[ctk.CTkFrame, str]] = []

        frame = self.create_container()
        self.add_title(frame, "Recent Files", use_pack=False).grid(
            row=0, column=0, columnspan=3, pady=(0, self.pady)
        )

        self.search_var = ctk.StringVar()
        entry = self.create_search_box(frame, self.search_var, "Search files...", self._filter)
        entry.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, self.gpady))
        self.add_tooltip(entry, "Filter recent files by name")

        start_row = 2
        for idx, path in enumerate(files, start=start_row):
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.grid(row=idx, column=0, columnspan=3, sticky="ew", pady=2)
            lbl = ctk.CTkLabel(row, text=path, anchor="w")
            self._mark_font_role(lbl, "normal")
            lbl.grid(row=0, column=0, sticky="ew", padx=self.gpadx)
            open_btn = ctk.CTkButton(row, text="Open", width=70, command=lambda p=path: open_path(p))
            open_btn.grid(row=0, column=1, padx=self.gpadx)
            folder_btn = ctk.CTkButton(row, text="Folder", width=70, command=lambda p=path: open_path(str(Path(p).parent)))
            folder_btn.grid(row=0, column=2, padx=self.gpadx)
            remove_btn = ctk.CTkButton(row, text="X", width=30, command=lambda p=path, r=row: self._remove(p, r))
            remove_btn.grid(row=0, column=3, padx=self.gpadx)
            self.rows.append((row, path))
            self.add_tooltip(open_btn, "Open file")
            self.add_tooltip(folder_btn, "Show in folder")
            self.add_tooltip(remove_btn, "Remove from list")

        frame.grid_columnconfigure(0, weight=1)

        self.center_window()

        # Apply current styling
        self.refresh_fonts()
        self.refresh_theme()

    def _filter(self) -> None:
        query = self.search_var.get().lower()
        for row, path in self.rows:
            if query in path.lower():
                row.grid()
            else:
                row.grid_remove()

    def _remove(self, path: str, row: ctk.CTkFrame) -> None:
        files = self.app.config.get("recent_files", [])
        if path in files:
            files.remove(path)
            self.app.config.set("recent_files", files)
            self.app.config.save()
            self.app.refresh_recent_files()
        row.destroy()

