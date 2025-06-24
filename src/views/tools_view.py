"""
Tools view - Various utilities and tools
"""
import customtkinter as ctk
from tkinter import filedialog, messagebox, simpledialog
import socket
import subprocess
import platform
import webbrowser
import json
import base64
from pathlib import Path
import re
from PIL import ImageGrab


class ToolsView(ctk.CTkFrame):
    """Tools and utilities view"""

    def __init__(self, parent, app):
        """Initialize tools view"""
        super().__init__(parent, corner_radius=0)
        self.app = app

        # Create scrollable frame
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Title
        title = ctk.CTkLabel(
            self.scroll_frame,
            text="🛠️ Tools & Utilities",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        title.pack(pady=(0, 20))

        # Create tool sections
        self._create_file_tools()
        self._create_system_tools()
        self._create_text_tools()
        self._create_network_tools()

    def _create_file_tools(self):
        """Create file manipulation tools"""
        section = self._create_section("📁 File Tools")

        tools = [
            ("Batch Rename", "Rename multiple files at once", self._batch_rename),
            ("File Converter", "Convert between file formats", self._file_converter),
            ("Duplicate Finder", "Find and remove duplicate files", self._duplicate_finder),
            ("File Splitter", "Split large files into parts", self._file_splitter),
            ("File Manager", "Copy, move or delete files", self._file_manager),
            ("Hash Calculator", "Compute file checksums", self._hash_calculator),
        ]

        for name, desc, func in tools:
            self._create_tool_item(section, name, desc, func)

    def _create_system_tools(self):
        """Create system tools"""
        section = self._create_section("💻 System Tools")

        tools = [
            ("System Info", "View system information", self._system_info),
            ("Process Manager", "Manage running processes", self._process_manager),
            ("Disk Cleanup", "Clean temporary files", self._disk_cleanup),
            (
                "Screenshot",
                "Capture screen to an image file",
                self._screenshot_tool,
            ),
            ("Registry Editor", "Edit system registry (Windows)", self._registry_editor),
        ]

        for name, desc, func in tools:
            self._create_tool_item(section, name, desc, func)

    def _create_text_tools(self):
        """Create text manipulation tools"""
        section = self._create_section("📝 Text Tools")

        tools = [
            ("Text Editor", "Advanced text editor", self._text_editor),
            ("Regex Tester", "Test regular expressions", self._regex_tester),
            ("JSON Formatter", "Format and validate JSON", self._json_formatter),
            ("Base64 Encoder", "Encode/decode Base64", self._base64_tool),
        ]

        for name, desc, func in tools:
            self._create_tool_item(section, name, desc, func)

    def _create_network_tools(self):
        """Create network tools"""
        section = self._create_section("🌐 Network Tools")

        tools = [
            ("Ping Tool", "Test network connectivity", self._ping_tool),
            ("Port Scanner", "Scan open ports", self._port_scanner),
            ("DNS Lookup", "Query DNS records", self._dns_lookup),
            ("Speed Test", "Test internet speed", self._speed_test),
        ]

        for name, desc, func in tools:
            self._create_tool_item(section, name, desc, func)

    def _create_section(self, title: str) -> ctk.CTkFrame:
        """Create a tool section"""
        # Section frame
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

    def _create_tool_item(self, parent, name: str, description: str, command):
        """Create a tool item"""
        # Tool frame
        tool_frame = ctk.CTkFrame(parent)
        tool_frame.pack(fill="x", padx=20, pady=5)

        # Left side - info
        info_frame = ctk.CTkFrame(tool_frame, fg_color="transparent")
        info_frame.pack(side="left", fill="x", expand=True, padx=20, pady=15)

        # Tool name
        name_label = ctk.CTkLabel(
            info_frame,
            text=name,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        )
        name_label.pack(fill="x")

        # Description
        desc_label = ctk.CTkLabel(
            info_frame,
            text=description,
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="w",
        )
        desc_label.pack(fill="x")

        # Launch button
        button = ctk.CTkButton(
            tool_frame,
            text="Launch",
            command=command,
            width=100,
        )
        button.pack(side="right", padx=20)

    # Tool implementations
    def _batch_rename(self):
        """Rename all files in a directory with a numeric sequence."""
        directory = filedialog.askdirectory(title="Select Folder", parent=self)
        if not directory:
            return
        prefix = simpledialog.askstring(
            "Batch Rename", "Filename prefix", parent=self
        )
        if prefix is None:
            return

        count = 0
        for idx, path in enumerate(Path(directory).iterdir(), start=1):
            if path.is_file():
                new_name = f"{prefix}_{idx}{path.suffix}"
                path.rename(path.with_name(new_name))
                count += 1

        messagebox.showinfo(
            "Batch Rename", f"Renamed {count} files in {directory}"
        )

    def _file_converter(self):
        """Convert a text file to upper case and save as new file."""
        src_file = filedialog.askopenfilename(
            title="Select Text File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            parent=self,
        )
        if not src_file:
            return
        dest_file = filedialog.asksaveasfilename(
            title="Save Converted File",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt")],
            parent=self,
        )
        if not dest_file:
            return

        try:
            data = Path(src_file).read_text()
            Path(dest_file).write_text(data.upper())
            messagebox.showinfo(
                "File Converter", f"File converted and saved to {dest_file}"
            )
        except Exception as exc:
            messagebox.showerror("File Converter", str(exc))

    def _duplicate_finder(self):
        """Find and optionally remove duplicate files within a folder."""
        directory = filedialog.askdirectory(title="Select Folder", parent=self)
        if not directory:
            return

        files = [p for p in Path(directory).rglob("*") if p.is_file()]
        total = len(files)

        hashes: dict[str, Path] = {}
        duplicates: dict[str, list[Path]] = {}
        for i, path in enumerate(files, 1):
            from src.utils import calc_hash

            digest = calc_hash(str(path))
            if digest in hashes:
                duplicates.setdefault(digest, []).append(path)
            else:
                hashes[digest] = path
            if self.app.status_bar is not None:
                self.app.status_bar.show_progress(i / total)

        if self.app.status_bar is not None:
            self.app.status_bar.hide_progress()

        if not duplicates:
            messagebox.showinfo("Duplicate Finder", "No duplicates found")
            return

        window = ctk.CTkToplevel(self)
        window.title("Duplicate Files")
        window.geometry("600x400")

        frame = ctk.CTkScrollableFrame(window)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        selections: list[tuple[ctk.BooleanVar, Path]] = []
        for paths in duplicates.values():
            for path in paths:
                var = ctk.BooleanVar(value=True)
                selections.append((var, path))
                ctk.CTkCheckBox(frame, text=str(path), variable=var).pack(anchor="w")

        def delete_selected() -> None:
            removed = 0
            for var, path in selections:
                if var.get():
                    try:
                        path.unlink()
                        removed += 1
                    except Exception:
                        continue
            messagebox.showinfo("Duplicate Finder", f"Removed {removed} files")
            window.destroy()

        ctk.CTkButton(window, text="Delete Selected", command=delete_selected).pack(pady=5)

    def _file_splitter(self):
        """Split a text file into smaller parts."""
        filename = filedialog.askopenfilename(parent=self)
        if not filename:
            return
        lines_per_part = simpledialog.askinteger(
            "File Splitter",
            "Lines per part",
            parent=self,
            minvalue=1,
        )
        if not lines_per_part:
            return

        lines = Path(filename).read_text().splitlines(True)
        base = Path(filename)
        for idx in range(0, len(lines), lines_per_part):
            part_lines = lines[idx:idx + lines_per_part]
            part_path = base.with_name(f"{base.stem}_part{idx // lines_per_part + 1}{base.suffix}")
            part_path.write_text("".join(part_lines))

        messagebox.showinfo("File Splitter", "File split successfully")

    def _file_manager(self):
        """Perform basic copy, move and delete operations."""
        from src.utils import (
            copy_file,
            move_file,
            delete_file,
            copy_dir,
            move_dir,
            delete_dir,
            list_files,
        )

        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Opening File Manager...", "info")
        window = ctk.CTkToplevel(self)
        window.title("File Manager")

        output = ctk.CTkTextbox(window, width=500, height=200)
        output.pack(padx=10, pady=10, fill="both", expand=True)

        def do_copy():
            is_dir = messagebox.askyesno("Copy", "Copy directory?", parent=window)
            if is_dir:
                src = filedialog.askdirectory(parent=window)
                if not src:
                    return
                dest_parent = filedialog.askdirectory(parent=window)
                if not dest_parent:
                    return
                dest = Path(dest_parent) / Path(src).name
                try:
                    copy_dir(src, dest, overwrite=True)
                    output.insert("end", f"Copied {src} -> {dest}\n")
                except Exception as exc:
                    messagebox.showerror("File Manager", str(exc))
            else:
                src = filedialog.askopenfilename(parent=window)
                if not src:
                    return
                dest = filedialog.asksaveasfilename(parent=window, initialfile=Path(src).name)
                if not dest:
                    return
                try:
                    copy_file(src, dest, overwrite=True)
                    output.insert("end", f"Copied {src} -> {dest}\n")
                except Exception as exc:
                    messagebox.showerror("File Manager", str(exc))

        def do_move():
            is_dir = messagebox.askyesno("Move", "Move directory?", parent=window)
            if is_dir:
                src = filedialog.askdirectory(parent=window)
                if not src:
                    return
                dest_parent = filedialog.askdirectory(parent=window)
                if not dest_parent:
                    return
                dest = Path(dest_parent) / Path(src).name
                try:
                    move_dir(src, dest, overwrite=True)
                    output.insert("end", f"Moved {src} -> {dest}\n")
                except Exception as exc:
                    messagebox.showerror("File Manager", str(exc))
            else:
                src = filedialog.askopenfilename(parent=window)
                if not src:
                    return
                dest = filedialog.asksaveasfilename(parent=window, initialfile=Path(src).name)
                if not dest:
                    return
                try:
                    move_file(src, dest, overwrite=True)
                    output.insert("end", f"Moved {src} -> {dest}\n")
                except Exception as exc:
                    messagebox.showerror("File Manager", str(exc))

        def do_delete():
            is_dir = messagebox.askyesno("Delete", "Delete directory?", parent=window)
            if is_dir:
                path = filedialog.askdirectory(parent=window)
                if not path:
                    return
                if messagebox.askyesno("Delete", f"Delete {path}?", parent=window):
                    try:
                        delete_dir(path)
                        output.insert("end", f"Deleted {path}\n")
                    except Exception as exc:
                        messagebox.showerror("File Manager", str(exc))
            else:
                path = filedialog.askopenfilename(parent=window)
                if not path:
                    return
                if messagebox.askyesno("Delete", f"Delete {path}?", parent=window):
                    try:
                        delete_file(path)
                        output.insert("end", f"Deleted {path}\n")
                    except Exception as exc:
                        messagebox.showerror("File Manager", str(exc))

        def do_list():
            directory = filedialog.askdirectory(parent=window)
            if not directory:
                return
            files = list_files(directory)
            output.insert("end", "\n".join(str(p) for p in files) + "\n")

        btn_frame = ctk.CTkFrame(window)
        btn_frame.pack(pady=5)
        ctk.CTkButton(btn_frame, text="Copy", command=do_copy).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Move", command=do_move).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Delete", command=do_delete).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="List Dir", command=do_list).pack(side="left", padx=5)

    def _system_info(self):
        """Show system information with CPU and memory details."""
        from src.utils import get_system_info

        info = "System Information:\n" + get_system_info()
        messagebox.showinfo("System Info", info)

    def _process_manager(self):
        """Display a simple cross-platform process manager."""
        import psutil

        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Opening Process Manager...", "info")

        window = ctk.CTkToplevel(self)
        window.title("Process Manager")

        text = ctk.CTkTextbox(window, width=600, height=400)
        text.pack(fill="both", expand=True, padx=10, pady=10)

        def refresh() -> None:
            """Refresh the process list sorted by CPU usage."""
            text.delete("1.0", "end")
            header = f"{'PID':>6} {'Name':<25} {'CPU%':>6} {'Memory MB':>10}\n"
            text.insert("end", header)
            text.insert("end", "-" * len(header) + "\n")
            processes = sorted(
                psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]),
                key=lambda p: p.info.get("cpu_percent", 0.0),
                reverse=True,
            )
            for proc in processes:
                pid = proc.info["pid"]
                name = proc.info["name"][:25]
                cpu = proc.info["cpu_percent"]
                mem = proc.info["memory_info"].rss / (1024 * 1024)
                line = f"{pid:6} {name:<25} {cpu:6.1f} {mem:10.1f}\n"
                text.insert("end", line)

        def schedule_refresh() -> None:
            refresh()
            window.after(5000, schedule_refresh)

        def kill_selected() -> None:
            """Prompt for a PID and attempt to terminate that process."""
            pid = simpledialog.askinteger("Terminate Process", "PID", parent=window)
            if pid is None:
                return
            try:
                psutil.Process(pid).terminate()
                refresh()
                messagebox.showinfo("Process Manager", f"Terminated PID {pid}")
            except psutil.NoSuchProcess:
                messagebox.showerror("Process Manager", f"PID {pid} not found")
            except Exception as exc:
                messagebox.showerror("Process Manager", str(exc))

        button_frame = ctk.CTkFrame(window, fg_color="transparent")
        button_frame.pack(pady=5)
        ctk.CTkButton(button_frame, text="Refresh", command=refresh, width=100).pack(side="left", padx=5)
        ctk.CTkButton(button_frame, text="Kill PID", command=kill_selected, width=100).pack(side="left", padx=5)

        schedule_refresh()

    def _disk_cleanup(self):
        """Remove temporary files in the system temp directory."""
        import shutil
        import tempfile

        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Cleaning temporary files...", "info")
        temp_dir = Path(tempfile.gettempdir())
        items = list(temp_dir.iterdir())
        total = len(items)
        count = 0
        for i, path in enumerate(items, 1):
            try:
                if path.is_file():
                    path.unlink()
                    count += 1
                elif path.is_dir():
                    shutil.rmtree(path)
                    count += 1
            except Exception:
                continue
            if self.app.status_bar is not None:
                self.app.status_bar.show_progress(i / total)

        if self.app.status_bar is not None:
            self.app.status_bar.hide_progress()

        messagebox.showinfo("Disk Cleanup", f"Removed {count} items from temp")

    def _screenshot_tool(self):
        """Capture the screen and save it to an image file."""
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save Screenshot",
            defaultextension=".png",
            filetypes=[("PNG files", "*.png")],
        )
        if not path:
            return
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Capturing screenshot...", "info")
        try:
            img = ImageGrab.grab()
            img.save(path, "PNG")
            if self.app.status_bar is not None:
                self.app.status_bar.set_message(f"Saved screenshot to {path}", "success")
        except Exception as exc:
            messagebox.showerror("Screenshot", str(exc))

    def _registry_editor(self):
        """Launch registry editor"""
        if platform.system() == "Windows":
            if self.app.status_bar is not None:
                self.app.status_bar.set_message("Opening Registry Editor...", "info")
            subprocess.Popen("regedit")
        else:
            if self.app.status_bar is not None:
                self.app.status_bar.set_message(
                    "Registry Editor is Windows only", "warning"
                )
            messagebox.showinfo(
                "Registry Editor",
                "The registry editor is only available on Windows",
            )

    def _text_editor(self):
        """Open a simple text editor window."""
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Opening Text Editor...", "info")
        window = ctk.CTkToplevel(self)
        window.title("Text Editor")

        toolbar = ctk.CTkFrame(window, fg_color="transparent")
        toolbar.pack(fill="x", padx=10, pady=(10, 0))

        textbox = ctk.CTkTextbox(window, width=600, height=400)
        textbox.pack(fill="both", expand=True, padx=10, pady=10)

        def open_file():
            filename = filedialog.askopenfilename(
                parent=window,
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            )
            if filename:
                try:
                    data = Path(filename).read_text()
                    textbox.delete("1.0", "end")
                    textbox.insert("1.0", data)
                    if self.app.status_bar is not None:
                        self.app.status_bar.set_message(f"Loaded {filename}", "success")
                except Exception as exc:
                    messagebox.showerror("Text Editor", str(exc))

        def save_file():
            filename = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                parent=window,
            )
            if filename:
                try:
                    Path(filename).write_text(textbox.get("1.0", "end-1c"))
                    if self.app.status_bar is not None:
                        self.app.status_bar.set_message(f"Saved {filename}", "success")
                except Exception as exc:
                    messagebox.showerror("Text Editor", str(exc))

        ctk.CTkButton(toolbar, text="Open", command=open_file, width=80).pack(side="left", padx=5)
        ctk.CTkButton(toolbar, text="Save", command=save_file, width=80).pack(side="left", padx=5)

    def _regex_tester(self):
        """Open a small regex testing utility."""
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Opening Regex Tester...", "info")
        window = ctk.CTkToplevel(self)
        window.title("Regex Tester")

        pattern_var = ctk.StringVar()
        ctk.CTkEntry(window, textvariable=pattern_var, width=400).pack(padx=10, pady=10)

        textbox = ctk.CTkTextbox(window, width=600, height=300)
        textbox.pack(padx=10, pady=10, fill="both", expand=True)

        result_label = ctk.CTkLabel(window, text="")
        result_label.pack(pady=5)

        def run_test():
            try:
                regex = re.compile(pattern_var.get())
                matches = regex.findall(textbox.get("1.0", "end-1c"))
                result_label.configure(text=f"Matches: {len(matches)}")
            except re.error as exc:
                result_label.configure(text=f"Error: {exc}")

        ctk.CTkButton(window, text="Test", command=run_test).pack(pady=5)

    def _json_formatter(self):
        """Format JSON in a simple editor."""
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Opening JSON Formatter...", "info")
        window = ctk.CTkToplevel(self)
        window.title("JSON Formatter")
        textbox = ctk.CTkTextbox(window, width=600, height=400)
        textbox.pack(fill="both", expand=True, padx=10, pady=10)

        def format_json():
            try:
                data = json.loads(textbox.get("1.0", "end-1c"))
                textbox.delete("1.0", "end")
                textbox.insert("1.0", json.dumps(data, indent=4))
            except Exception as exc:
                messagebox.showerror("JSON Formatter", str(exc))

        ctk.CTkButton(window, text="Format", command=format_json).pack(pady=10)

    def _base64_tool(self):
        """Encode or decode Base64 strings."""
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Opening Base64 Tool...", "info")
        window = ctk.CTkToplevel(self)
        window.title("Base64 Tool")

        input_box = ctk.CTkTextbox(window, width=600, height=150)
        input_box.pack(padx=10, pady=5, fill="both", expand=True)

        output_box = ctk.CTkTextbox(window, width=600, height=150)
        output_box.pack(padx=10, pady=5, fill="both", expand=True)

        def encode():
            data = input_box.get("1.0", "end-1c").encode()
            output_box.delete("1.0", "end")
            output_box.insert("1.0", base64.b64encode(data).decode())

        def decode():
            try:
                data = base64.b64decode(input_box.get("1.0", "end-1c"))
                output_box.delete("1.0", "end")
                output_box.insert("1.0", data.decode())
            except Exception as exc:
                messagebox.showerror("Base64", str(exc))

        btn_frame = ctk.CTkFrame(window, fg_color="transparent")
        btn_frame.pack()
        ctk.CTkButton(btn_frame, text="Encode", command=encode).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Decode", command=decode).pack(side="left", padx=10)

    def _hash_calculator(self):
        """Calculate file checksums using various algorithms."""
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Opening Hash Calculator...", "info")
        window = ctk.CTkToplevel(self)
        window.title("Hash Calculator")

        file_var = ctk.StringVar()

        entry = ctk.CTkEntry(window, textvariable=file_var, width=400)
        entry.pack(padx=10, pady=(10, 5))

        def browse() -> None:
            path = filedialog.askopenfilename(parent=window)
            if path:
                file_var.set(path)

        browse_btn = ctk.CTkButton(window, text="Browse", command=browse)
        browse_btn.pack(pady=5)

        algo_var = ctk.StringVar(value="md5")
        ctk.CTkOptionMenu(
            window, values=["md5", "sha1", "sha256"], variable=algo_var
        ).pack(pady=5)

        output = ctk.CTkTextbox(window, width=500, height=100)
        output.pack(padx=10, pady=10, fill="both", expand=True)

        def compute() -> None:
            from src.utils import calc_hash

            path = file_var.get()
            if not path:
                messagebox.showwarning("Hash", "Choose a file", parent=window)
                return
            try:
                digest = calc_hash(path, algo_var.get())
                output.delete("1.0", "end")
                output.insert("1.0", digest)
            except Exception as exc:
                messagebox.showerror("Hash", str(exc), parent=window)

        ctk.CTkButton(window, text="Compute", command=compute).pack(pady=5)

    def _ping_tool(self):
        """Launch ping tool"""
        host = simpledialog.askstring("Ping", "Enter host to ping", parent=self)
        if not host:
            return
        if self.app.status_bar is not None:
            self.app.status_bar.set_message(f"Pinging {host}...", "info")
        count_flag = "-n" if platform.system() == "Windows" else "-c"
        try:
            result = subprocess.run(["ping", count_flag, "4", host], capture_output=True, text=True, timeout=10)
            messagebox.showinfo("Ping Result", result.stdout or result.stderr)
        except Exception as exc:
            messagebox.showerror("Ping Error", str(exc))

    def _port_scanner(self):
        """Launch a simple port scanner supporting ranges."""
        host = simpledialog.askstring("Port Scanner", "Host", parent=self)
        if not host:
            return
        rng = simpledialog.askstring(
            "Port Scanner",
            "Port or range (e.g. 22 or 20-25)",
            parent=self,
        )
        if not rng:
            return

        try:
            if "-" in rng:
                start, end = [int(p) for p in rng.split("-", 1)]
            else:
                start = end = int(rng)
        except ValueError:
            messagebox.showerror("Port Scanner", "Invalid port specification")
            return

        from src.utils import async_scan_ports
        import threading
        import asyncio

        def progress(value: float | None) -> None:
            if value is None:
                if self.app.status_bar is not None:
                    self.app.window.after(0, self.app.status_bar.hide_progress)
            else:
                if self.app.status_bar is not None:
                    self.app.window.after(0, lambda: self.app.status_bar.show_progress(value))

        def run_scan() -> None:
            open_ports = asyncio.run(async_scan_ports(host, start, end, progress))

            def show_result() -> None:
                if open_ports:
                    ports = ", ".join(str(p) for p in open_ports)
                    messagebox.showinfo(
                        "Port Scanner",
                        f"Open ports on {host}: {ports}",
                    )
                else:
                    messagebox.showinfo(
                        "Port Scanner",
                        f"No open ports found on {host} in range {start}-{end}",
                    )

            self.app.window.after(0, show_result)

        threading.Thread(target=run_scan, daemon=True).start()

    def _dns_lookup(self):
        """Launch DNS lookup"""
        domain = simpledialog.askstring("DNS Lookup", "Domain", parent=self)
        if not domain:
            return
        try:
            info = socket.gethostbyname_ex(domain)
            result = "\n".join(info[2])
            messagebox.showinfo("DNS Lookup", f"IPs for {domain}:\n{result}")
        except Exception as exc:
            messagebox.showerror("DNS Lookup", str(exc))

    def _speed_test(self):
        """Launch speed test"""
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Opening Speed Test...", "info")
        webbrowser.open("https://fast.com")
