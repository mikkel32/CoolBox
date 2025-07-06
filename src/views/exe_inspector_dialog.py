from __future__ import annotations

"""Dialog showing executable details with a terminal style interface."""

import datetime
import shlex
from pathlib import Path
from typing import List, Dict

import customtkinter as ctk

from .base_dialog import BaseDialog
from ..utils.process_utils import run_command_ex

# Reuse helpers from the CLI inspector
from scripts import exe_inspector as inspector


class ExeInspectorDialog(BaseDialog):
    """Display executable information and allow running shell commands."""

    def __init__(self, app, exe_path: str) -> None:
        super().__init__(app, title="Executable Inspector", geometry="700x500", resizable=(True, True))
        self.path = Path(exe_path)

        container = self.create_container()
        self.output = ctk.CTkTextbox(
            container,
            fg_color="#000000",
            text_color="#00ff00",
        )
        self.output.configure(font=("Courier", 12))
        self.output.pack(fill="both", expand=True)

        entry_frame = ctk.CTkFrame(container, fg_color="transparent")
        entry_frame.pack(fill="x", pady=(10, 0))
        self.entry = ctk.CTkEntry(entry_frame)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self._on_enter)
        refresh = ctk.CTkButton(entry_frame, text="Refresh", width=100, command=self.refresh)
        refresh.pack(side="right", padx=5)

        self.refresh()
        self.center_window()
        self.refresh_fonts()
        self.refresh_theme()

    # ------------------------------------------------------------------ helpers
    def _write_lines(self, lines: List[str]) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        for line in lines:
            self.output.insert("end", line + "\n")
        self.output.see("end")
        self.output.configure(state="disabled")

    # ------------------------------------------------------------------ actions
    def refresh(self) -> None:
        """Gather fresh information and render it."""
        info: Dict[str, str] = inspector.gather_info(self.path)
        procs = inspector._processes_for(self.path) if self.path.exists() else []
        ports = inspector._ports_for([p.pid for p in procs]) if procs else {}
        strings = inspector._extract_strings(self.path, limit=10)

        lines: List[str] = []
        lines.append("# Executable Info")
        for k, v in info.items():
            lines.append(f"{k}: {v}")
        if procs:
            lines.append("\n# Running Processes")
            for p in procs:
                try:
                    lines.append(f"{p.pid} {p.name()}")
                except Exception:
                    continue
        if ports:
            lines.append("\n# Listening Ports")
            for port, names in ports.items():
                lines.append(f"{port} {', '.join(names)}")
        if strings:
            lines.append("\n# Strings")
            for s in strings:
                lines.append(s)

        self._write_lines(lines)

    def _on_enter(self, event=None) -> None:
        cmd = self.entry.get().strip()
        if not cmd:
            return
        ts = datetime.datetime.now().strftime("[%H:%M:%S] $ ")
        self.output.configure(state="normal")
        self.output.insert("end", ts + cmd + "\n")
        out, rc = run_command_ex(shlex.split(cmd), capture=True, check=False)
        if out is None:
            self.output.insert("end", "<error>\n")
        elif out:
            self.output.insert("end", out + ("" if out.endswith("\n") else "\n"))
        else:
            self.output.insert("end", "<no output>\n")
        if rc is not None:
            self.output.insert("end", f"[exit {rc}]\n")
        self.output.see("end")
        self.output.configure(state="disabled")
        self.entry.delete(0, "end")
