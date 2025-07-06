from __future__ import annotations

import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
import subprocess

import customtkinter as ctk

from .base_dialog import BaseDialog


class ExeTesterDialog(BaseDialog):
    """UI wrapper around ``scripts/exe_tester.py``."""

    def __init__(self, app):
        super().__init__(app, title="Executable Tester", geometry="800x600", resizable=(True, True))
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.add_title(self, "Executable Tester", use_pack=False).grid(
            row=0, column=0, columnspan=2, pady=(10, 5)
        )

        left = ctk.CTkFrame(self)
        left.grid(row=1, column=0, sticky="ns", padx=(self.padx, 0), pady=self.pady)
        left.grid_columnconfigure(1, weight=1)

        self.exe_var = ctk.StringVar()
        self.grid_file_entry(left, "Executable:", self.exe_var, 0, self._browse)

        self.iter_var = ctk.IntVar(value=5)
        self.grid_entry(left, "Iterations:", self.iter_var, 1, width=80)

        self.runtime_var = ctk.StringVar(value="2.0")
        self.grid_entry(left, "Runtime (s):", self.runtime_var, 2, width=80)

        self.hidden_var = ctk.BooleanVar()
        self.grid_checkbox(left, "Hide Window", self.hidden_var, 3)

        self.grid_button(left, "Run Test", self._run_test, 4)

        right = ctk.CTkFrame(self)
        right.grid(row=1, column=1, sticky="nsew", padx=(0, self.padx), pady=self.pady)
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self.output_box = ctk.CTkTextbox(right)
        self.output_box.grid(row=0, column=0, sticky="nsew")
        self.output_box.configure(state="disabled")

    # ------------------------------------------------------------------ helpers
    def _browse(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Select Executable")
        if path:
            self.exe_var.set(path)

    def _run_test(self) -> None:
        exe = self.exe_var.get()
        if not exe:
            messagebox.showwarning("Executable Tester", "Choose an executable", parent=self)
            return
        try:
            iterations = int(self.iter_var.get())
        except Exception:
            messagebox.showerror("Executable Tester", "Invalid iterations", parent=self)
            return
        try:
            runtime = float(self.runtime_var.get())
        except Exception:
            messagebox.showerror("Executable Tester", "Invalid runtime", parent=self)
            return
        self.output_box.configure(state="normal")
        self.output_box.delete("1.0", "end")
        self.output_box.configure(state="disabled")
        thread = threading.Thread(
            target=self._run_process,
            args=(exe, iterations, runtime, self.hidden_var.get()),
            daemon=True,
        )
        thread.start()

    def _run_process(self, exe: str, iterations: int, runtime: float, hidden: bool) -> None:
        script = Path(__file__).resolve().parents[2] / "scripts" / "exe_tester.py"
        cmd = [sys.executable, str(script), exe, "--iterations", str(iterations), "--runtime", str(runtime)]
        if hidden:
            cmd.append("--hidden")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            self.output_box.after(0, lambda: messagebox.showerror("Executable Tester", str(exc), parent=self))
            return
        assert proc.stdout is not None
        for line in proc.stdout:
            self.output_box.after(0, self._append_output, line)
        proc.wait()
        self.output_box.after(0, self._append_output, f"\nProcess exited with code {proc.returncode}\n")

    def _append_output(self, text: str) -> None:
        self.output_box.configure(state="normal")
        self.output_box.insert("end", text)
        self.output_box.see("end")
        self.output_box.configure(state="disabled")
