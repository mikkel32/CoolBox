from __future__ import annotations

import webbrowser
from pathlib import Path

import customtkinter as ctk


class ModernErrorDialog(ctk.CTkToplevel):
    """Modern error dialog using CustomTkinter widgets."""

    def __init__(self, master: ctk.CTkBaseClass, message: str, details: str, log_file: Path | None = None):
        super().__init__(master)
        self.title("Unexpected Error")
        self.resizable(True, True)

        ctk.CTkLabel(self, text=message, wraplength=480, justify="left").pack(padx=20, pady=(20, 10))

        self._details = ctk.CTkTextbox(self, width=480, height=200)
        self._details.insert("1.0", details)
        self._details.configure(state="disabled")
        self._details.pack_forget()

        btn_row = ctk.CTkFrame(self)
        btn_row.pack(pady=(0, 20))

        self._toggle_btn = ctk.CTkButton(btn_row, text="Show details", command=self._toggle)
        self._toggle_btn.pack(side="left", padx=5)

        if log_file is not None:
            ctk.CTkButton(
                btn_row,
                text="Open Log",
                command=lambda: webbrowser.open(log_file.as_uri()),
            ).pack(side="left", padx=5)

        ctk.CTkButton(btn_row, text="Copy", command=self._copy).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="Close", command=self.destroy).pack(side="left", padx=5)

        self.grab_set()
        self.focus_force()

    def _toggle(self) -> None:
        if self._details.winfo_manager():
            self._details.pack_forget()
            self._toggle_btn.configure(text="Show details")
        else:
            self._details.pack(fill="both", expand=True, padx=20, pady=(0, 10))
            self._toggle_btn.configure(text="Hide details")

    def _copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._details.get("1.0", "end").strip())
