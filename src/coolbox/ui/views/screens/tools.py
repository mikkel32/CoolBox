"""
Tools view - Various utilities and tools
"""
from __future__ import annotations

import base64
import json
import platform
import re
import socket
import subprocess
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal, TYPE_CHECKING, cast

import customtkinter as ctk
from tkinter import filedialog, messagebox, simpledialog
try:
    from PIL import ImageGrab
except ImportError:  # pragma: no cover - runtime dependency check
    from coolbox.ensure_deps import ensure_pillow

    pil = ensure_pillow()
    ImageGrab = pil.ImageGrab  # type: ignore[attr-defined]
from ..base import BaseView
from ...components.widgets import info_label
from coolbox.plugins.worker import (
    PluginMetricsSnapshot,
    PluginTraceRecord,
    get_global_plugin_metrics,
)
from coolbox.utils import security

if TYPE_CHECKING:  # pragma: no cover - typing helpers
    from coolbox.utils.network import PortInfo, PortResult


ToolCallback = Callable[[], None]
ProgressCallback = Callable[[float | None], None]
HashAlgorithm = Literal["md5", "sha1", "sha256"]


class ToolsView(BaseView):
    """Tools and utilities view"""

    def __init__(self, parent, app):
        """Initialize tools view"""
        super().__init__(parent, app)

        # Layout tabs for utilities and health dashboard
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=self.padx, pady=self.pady)

        utilities_tab = self.tabview.add("Utilities")
        self.health_tab = self.tabview.add("Health")

        self.scroll_frame = ctk.CTkScrollableFrame(utilities_tab)
        self.scroll_frame.pack(fill="both", expand=True)

        self.add_title(self.scroll_frame, "🛠️ Tools & Utilities")

        self.search_var = ctk.StringVar()
        self.search_entry = self.create_search_box(
            self.scroll_frame,
            self.search_var,
            "Search tools...",
            self._filter_tools,
        )
        self.search_entry.pack(fill="x", padx=20, pady=(0, 20))
        self.add_tooltip(self.search_entry, "Filter tools by name")
        self.app.window.bind("<Control-f>", lambda e: self._focus_search())
        self._tool_items: list[
            tuple[
                ctk.CTkFrame,
                str,
                str,
                ctk.CTkLabel,
                ctk.CTkLabel,
                ToolCallback,
                str,
                str,
            ]
        ] = []
        self._security_center_job: str | None = None

        # Create tool sections
        self._create_file_tools()
        self._create_system_tools()
        self._create_text_tools()
        self._create_network_tools()

        self.no_results = ctk.CTkLabel(
            self.scroll_frame, text="No tools found", font=self.font
        )
        self.no_results.pack_forget()

        # Health dashboard elements
        self._metrics_rows: list[ctk.CTkFrame] = []
        self._metrics_header = ctk.CTkFrame(self.health_tab)
        self._metrics_header.pack(fill="x", padx=20, pady=(20, 10))
        self._metrics_title = ctk.CTkLabel(
            self._metrics_header,
            text="Plugin Health Dashboard",
            font=self.section_font,
        )
        self._metrics_title.pack(side="left")
        self._refresh_button = ctk.CTkButton(
            self._metrics_header,
            text="Refresh",
            command=self._refresh_metrics,
            width=100,
        )
        self._refresh_button.pack(side="right")
        self.metrics_container = ctk.CTkScrollableFrame(self.health_tab)
        self.metrics_container.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self._metrics_empty = ctk.CTkLabel(
            self.metrics_container,
            text="No plugin activity recorded yet.",
            font=self.font,
        )

        # Apply current styling
        self.refresh_fonts()
        self.refresh_theme()
        self._refresh_metrics()

    def refresh_theme(self) -> None:  # type: ignore[override]
        super().refresh_theme()

    def get_tools(self) -> list[tuple[str, str, ToolCallback]]:
        """Return a list of available tools and their launch callbacks."""
        tools: list[tuple[str, str, ToolCallback]] = []
        for _, _, _, name_lbl, desc_lbl, cmd, *_ in self._tool_items:
            tools.append((name_lbl.cget("text"), desc_lbl.cget("text"), cmd))
        return tools

    def _filter_tools(self) -> None:
        query = self.search_var.get().lower()
        accent = self.app.theme.get_theme().get("accent_color", "#1faaff")
        for frame, name, desc, name_lbl, desc_lbl, _, default_name, default_desc in self._tool_items:
            match = query and (query in name or query in desc)
            if match:
                if not frame.winfo_viewable():
                    frame.pack(fill="x", padx=20, pady=5)
                name_lbl.configure(text_color=accent)
                desc_lbl.configure(text_color=accent)
            else:
                name_lbl.configure(text_color=default_name)
                desc_lbl.configure(text_color=default_desc)
                if frame.winfo_viewable() and query:
                    frame.pack_forget()
                elif not frame.winfo_viewable() and not query:
                    frame.pack(fill="x", padx=20, pady=5)

        visible = any(frame.winfo_viewable() for frame, *_ in self._tool_items)
        if visible:
            if self.no_results.winfo_ismapped():
                self.no_results.pack_forget()
        else:
            self.no_results.pack(pady=20)

    def _refresh_metrics(self) -> None:
        registry = get_global_plugin_metrics()
        snapshot = registry.snapshot()
        for row in self._metrics_rows:
            row.destroy()
        self._metrics_rows.clear()
        if not snapshot:
            if not self._metrics_empty.winfo_ismapped():
                self._metrics_empty.pack(pady=40)
            return
        if self._metrics_empty.winfo_ismapped():
            self._metrics_empty.pack_forget()
        for plugin_id, metrics in sorted(snapshot.items()):
            row = ctk.CTkFrame(self.metrics_container)
            row.pack(fill="x", padx=10, pady=6)
            header = ctk.CTkFrame(row, fg_color="transparent")
            header.pack(fill="x", padx=10, pady=(10, 4))
            title = ctk.CTkLabel(header, text=plugin_id, font=self.section_font)
            title.pack(side="left")
            summary = ctk.CTkLabel(
                row,
                text=self._format_metrics_summary(metrics),
                justify="left",
            )
            summary.pack(fill="x", padx=10)
            traces_frame = ctk.CTkFrame(row, fg_color="transparent")
            traces_frame.pack(fill="x", padx=10, pady=(4, 10))
            traces_label = ctk.CTkLabel(
                traces_frame, text="Recent Invocations:", font=self.font
            )
            traces_label.pack(anchor="w")
            recent_traces = list(metrics.recent_traces)[-5:][::-1]
            if not recent_traces:
                ctk.CTkLabel(
                    traces_frame,
                    text="No recent invocations.",
                    font=self.font,
                ).pack(anchor="w", padx=4, pady=2)
            else:
                for record in recent_traces:
                    button = ctk.CTkButton(
                        traces_frame,
                        text=self._format_trace_button(record),
                        anchor="w",
                        command=lambda r=record, pid=plugin_id: self._show_trace_detail(pid, r),
                    )
                    button.pack(fill="x", padx=4, pady=2)
            self._metrics_rows.append(row)
        self.apply_fonts(self.metrics_container)

    def _format_metrics_summary(self, metrics: PluginMetricsSnapshot) -> str:
        error_rate = f"{metrics.error_rate * 100:.1f}%" if metrics.invocations else "0.0%"
        latency_line = (
            f"Latency p50: {self._format_latency(metrics.latency_p50)}    "
            f"p95: {self._format_latency(metrics.latency_p95)}    "
            f"p99: {self._format_latency(metrics.latency_p99)}"
        )
        if metrics.memory_high_water is None:
            memory = "—"
        else:
            memory = f"{metrics.memory_high_water / (1024 * 1024):.1f} MiB"
        lines = [
            f"Invocations: {metrics.invocations}    Errors: {metrics.errors} ({error_rate})",
            latency_line,
            f"Memory high-water: {memory}    Capability denials: {metrics.capability_denials}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_latency(value: float | None) -> str:
        if value is None:
            return "—"
        return f"{value * 1000.0:.1f} ms"

    def _format_trace_button(self, record: PluginTraceRecord) -> str:
        timestamp = datetime.fromtimestamp(record.timestamp).strftime("%H:%M:%S")
        duration = self._format_latency(record.duration)
        status = record.status.replace("_", " ").title()
        parts = [timestamp, record.method, status, duration]
        if record.trace_id:
            parts.append(record.trace_id[:8])
        return " • ".join(parts)

    def _show_trace_detail(self, plugin_id: str, record: PluginTraceRecord) -> None:
        timestamp = datetime.fromtimestamp(record.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        detail_lines = [
            f"Plugin: {plugin_id}",
            f"Method: {record.method}",
            f"Status: {record.status}",
            f"Recorded: {timestamp}",
            f"Duration: {self._format_latency(record.duration)}",
        ]
        if record.error:
            detail_lines.append(f"Error: {record.error}")
        if record.trace_id:
            detail_lines.append(f"Trace ID: {record.trace_id}")
        message = "\n".join(detail_lines)
        if record.trace_id:
            try:
                self.clipboard_clear()
                self.clipboard_append(record.trace_id)
                message += "\n\nTrace ID copied to clipboard."
            except Exception:
                message += "\n\nTrace ID available for copy."
        messagebox.showinfo("Trace Details", message, parent=self)

    def _focus_search(self) -> None:
        """Focus the tools search box when active."""
        if self.app.current_view == "tools":
            self.search_entry.focus_set()

    def _create_file_tools(self):
        """Create file manipulation tools"""
        section, body = self.add_collapsible_section(
            self.scroll_frame, "📁 File Tools", key="tools_file"
        )

        tools = [
            ("Batch Rename", "Rename multiple files at once", self._batch_rename),
            ("File Converter", "Convert between file formats", self._file_converter),
            ("Duplicate Finder", "Find and remove duplicate files", self._duplicate_finder),
            ("File Splitter", "Split large files into parts", self._file_splitter),
            ("File Manager", "Copy, move or delete files", self._file_manager),
            ("Hash Calculator", "Compute file checksums", self._hash_calculator),
        ]

        for name, desc, func in tools:
            self._create_tool_item(body, name, desc, func)

    def _create_system_tools(self):
        """Create system tools"""
        section, body = self.add_collapsible_section(
            self.scroll_frame, "💻 System Tools", key="tools_system"
        )

        tools = [
            ("System Info", "View system information", self._system_info),
            ("Process Manager", "Manage running processes", self._process_manager),
            ("Force Quit", "Forcefully terminate a process", self._force_quit),
            ("Disk Cleanup", "Clean temporary files", self._disk_cleanup),
            (
                "Screenshot",
                "Capture screen to an image file",
                self._screenshot_tool,
            ),
            ("Registry Editor", "Edit system registry (Windows)", self._registry_editor),
            (
                "Launch VM Debug",
                "Run CoolBox in a VM and wait for debugger",
                self._launch_vm_debug,
            ),
            (
                "Executable Inspector",
                "Inspect an executable file",
                self._exe_inspector,
            ),
            (
                "Security Center",
                "Toggle Firewall and Defender",
                self._security_center,
            ),
        ]

        for name, desc, func in tools:
            self._create_tool_item(body, name, desc, func)

        self._update_security_center_entry()

    def _update_security_center_entry(self) -> None:
        if not self.winfo_exists():
            return
        pending = security.get_permission_manager().pending_count()
        description = "Toggle Firewall and Defender"
        if pending:
            description += f" • Pending capability requests: {pending}"
        for _, _, _, name_lbl, desc_lbl, *_ in self._tool_items:
            if name_lbl.cget("text") == "Security Center":
                desc_lbl.configure(text=description)
                break
        if self._security_center_job is not None:
            try:
                self.after_cancel(self._security_center_job)
            except Exception:
                pass
        self._security_center_job = self.after(60000, self._update_security_center_entry)

    def _create_text_tools(self):
        """Create text manipulation tools"""
        section, body = self.add_collapsible_section(
            self.scroll_frame, "📝 Text Tools", key="tools_text"
        )

        tools = [
            ("Text Editor", "Advanced text editor", self._text_editor),
            ("Regex Tester", "Test regular expressions", self._regex_tester),
            ("JSON Formatter", "Format and validate JSON", self._json_formatter),
            ("Base64 Encoder", "Encode/decode Base64", self._base64_tool),
        ]

        for name, desc, func in tools:
            self._create_tool_item(body, name, desc, func)

    def _create_network_tools(self):
        """Create network tools"""
        section, body = self.add_collapsible_section(
            self.scroll_frame, "🌐 Network Tools", key="tools_network"
        )

        tools = [
            ("Ping Tool", "Test network connectivity", self._ping_tool),
            ("Port Scanner", "Scan open ports", self._port_scanner),
            ("Network Scanner", "Scan multiple hosts", self._network_scan),
            (
                "Auto Network Scan",
                "Automatically scan connected networks",
                self._auto_network_scan,
            ),
            ("DNS Lookup", "Query DNS records", self._dns_lookup),
            ("Speed Test", "Test internet speed", self._speed_test),
        ]

        for name, desc, func in tools:
            self._create_tool_item(body, name, desc, func)

    def _create_tool_item(self, parent, name: str, description: str, command):
        """Create a tool item"""
        # Tool frame
        tool_frame = ctk.CTkFrame(parent)
        tool_frame.pack(fill="x", padx=20, pady=5)
        tool_frame.grid_columnconfigure(0, weight=1)

        info_frame = ctk.CTkFrame(tool_frame, fg_color="transparent")
        info_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=15)

        name_label = ctk.CTkLabel(
            info_frame,
            text=name,
            font=self.section_font,
            anchor="w",
        )
        name_label.pack(fill="x")
        default_name_color = name_label.cget("text_color")

        desc_label = info_label(info_frame, description, font=self.font)
        desc_label.pack(fill="x")
        default_desc_color = desc_label.cget("text_color")

        button = self.grid_button(
            tool_frame,
            "Launch",
            lambda cmd=command, name=name: self._safe_launch(name, cmd),
            0,
            column=1,
            columnspan=1,
            width=100,
        )
        self.add_tooltip(button, f"Open {name}")
        self._tool_items.append(
            (
                tool_frame,
                name.lower(),
                description.lower(),
                name_label,
                desc_label,
                command,
                default_name_color,
                default_desc_color,
            )
        )

    def _safe_launch(self, name: str, func: ToolCallback) -> None:
        """Run *func* in a background thread and surface errors gracefully."""

        self.app.thread_manager.run_tool(
            name,
            func,
            window=self.app.window,
            status_bar=self.app.status_bar,
        )

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

        # Group by size so we only hash files that could be duplicates
        size_map: dict[int, list[Path]] = {}
        for path in files:
            size_map.setdefault(path.stat().st_size, []).append(path)

        groups = [g for g in size_map.values() if len(g) > 1]

        hashes: dict[str, Path] = {}
        duplicates: dict[str, list[Path]] = {}

        from coolbox.utils.cache import CacheManager
        from coolbox.utils.hash_utils import calc_hashes

        cache_file = self.app.config.cache_dir / "hash_cache.json"
        hash_cache = CacheManager[dict](cache_file)

        def update(value: float | None) -> None:
            if self.app.status_bar is not None:
                if value is None:
                    self.app.status_bar.hide_progress()
                else:
                    self.app.status_bar.show_progress(value)

        paths = [str(p) for group in groups for p in group]
        digest_map = calc_hashes(paths, cache=hash_cache, progress=update)

        for path_str, digest in digest_map.items():
            path = Path(path_str)
            if digest in hashes:
                duplicates.setdefault(digest, []).append(path)
            else:
                hashes[digest] = path

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
        self.center_window(window)

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
        from coolbox.utils import (
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
                    copy_dir(src, str(dest), overwrite=True)
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
                    move_dir(src, str(dest), overwrite=True)
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
        self.center_window(window)

    def _system_info(self):
        """Open the enhanced System Info dialog."""
        from ..dialogs.system_info import SystemInfoDialog

        SystemInfoDialog(self.app)

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

        refresh_job: str | None = None

        def schedule_refresh() -> None:
            nonlocal refresh_job
            if not window.winfo_exists():
                return
            refresh()
            refresh_job = window.after(5000, schedule_refresh)

        def on_close() -> None:
            if refresh_job is not None:
                window.after_cancel(refresh_job)
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", on_close)

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
        self.center_window(window)

    def _force_quit(self) -> None:
        """Open the advanced Force Quit dialog."""
        self.app.open_force_quit()

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

    def _launch_vm_debug(self) -> None:
        """Start CoolBox inside a VM for debugging."""
        if not messagebox.askyesno(
            "Launch VM Debug",
            "Start CoolBox in a VM and wait for the debugger?",
        ):
            return

        open_code = messagebox.askyesno(
            "Visual Studio Code",
            "Open VS Code once the VM starts for easier debugging?",
        )

        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Launching VM...", "info")

        def run() -> None:
            from coolbox.utils import launch_vm_debug

            try:
                launch_vm_debug(open_code=open_code)
            except Exception as exc:
                messagebox.showerror("VM Debug", str(exc))
            finally:
                if self.app.status_bar is not None:
                    self.app.window.after(0, self.app.status_bar.hide_progress)

        threading.Thread(target=run, daemon=True).start()

    def _exe_inspector(self) -> None:
        """Launch the executable inspector."""
        exe = filedialog.askopenfilename(
            parent=self,
            title="Select Executable",
            filetypes=[("Executables", "*.exe"), ("All files", "*.*")],
        )
        if not exe:
            return
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Launching Exe Inspector...", "info")
        try:
            from ..dialogs.exe_inspector import ExeInspectorDialog

            ExeInspectorDialog(self.app, exe)
        except Exception as exc:
            messagebox.showerror("Executable Inspector", str(exc))

    def _security_center(self) -> None:
        """Open the Security Center dialog."""
        self.app.open_security_center()

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
        self.center_window(window)

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
        self.center_window(window)

    def _json_formatter(self):
        """Format JSON in a simple editor."""
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Opening JSON Formatter...", "info")
        window = ctk.CTkToplevel(self)
        window.title("JSON Formatter")
        frame = ctk.CTkFrame(window)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        frame.grid_rowconfigure(0, weight=1)
        textbox = self.grid_textbox(frame, "JSON:", 0, height=400)

        def format_json():
            try:
                data = json.loads(textbox.get("1.0", "end-1c"))
                textbox.delete("1.0", "end")
                textbox.insert("1.0", json.dumps(data, indent=4))
            except Exception as exc:
                messagebox.showerror("JSON Formatter", str(exc))

        ctk.CTkButton(window, text="Format", command=format_json).pack(pady=10)
        self.center_window(window)

    def _base64_tool(self):
        """Encode or decode Base64 strings."""
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Opening Base64 Tool...", "info")
        window = ctk.CTkToplevel(self)
        window.title("Base64 Tool")

        frame = ctk.CTkFrame(window)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        input_box = self.grid_textbox(frame, "Input:", 0, height=150)
        output_box = self.grid_textbox(frame, "Output:", 1, height=150)

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
        self.center_window(window)

    def _hash_calculator(self):
        """Calculate file checksums using various algorithms."""
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("Opening Hash Calculator...", "info")
        window = ctk.CTkToplevel(self)
        window.title("Hash Calculator")

        file_var = ctk.StringVar()
        file_frame = ctk.CTkFrame(window)
        file_frame.pack(fill="x", padx=10, pady=(10, 5))

        def browse() -> None:
            path = filedialog.askopenfilename(parent=window)
            if path:
                file_var.set(path)

        self.grid_file_entry(
            file_frame, "File:", file_var, 0, browse
        )

        algo_var = ctk.StringVar(value="md5")
        ctk.CTkOptionMenu(
            window, values=["md5", "sha1", "sha256"], variable=algo_var
        ).pack(pady=5)

        output = ctk.CTkTextbox(window, width=500, height=100)
        output.pack(padx=10, pady=10, fill="both", expand=True)

        def compute() -> None:
            from coolbox.utils.hash_utils import calc_hash

            path = file_var.get()
            if not path:
                messagebox.showwarning("Hash", "Choose a file", parent=window)
                return
            try:
                algo = cast(HashAlgorithm, algo_var.get())
                digest = calc_hash(path, algo)
                output.delete("1.0", "end")
                output.insert("1.0", digest)
            except Exception as exc:
                messagebox.showerror("Hash", str(exc), parent=window)

        ctk.CTkButton(window, text="Compute", command=compute).pack(pady=5)
        self.center_window(window)

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
            "Port or range (22, 20-25, ssh,http, 20-30:2, top100)",
            parent=self,
        )
        if not rng:
            return

        from coolbox.utils import parse_ports, ports_as_range
        is_top = rng.lower().startswith("top")
        try:
            ports = parse_ports(rng)
        except Exception:
            messagebox.showerror("Port Scanner", "Invalid port specification")
            return
        start_end = ports_as_range(ports)

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
            ttl = self.app.config.get("scan_cache_ttl", 300)
            concurrency = self.app.config.get("scan_concurrency", 100)
            timeout = self.app.config.get("scan_timeout", 0.5)
            fam_opt = self.app.config.get("scan_family", "auto").lower()
            fam = None
            if fam_opt == "ipv4":
                fam = socket.AF_INET
            elif fam_opt == "ipv6":
                fam = socket.AF_INET6
            with_services = self.app.config.get("scan_services", False)
            with_banner = self.app.config.get("scan_banner", False)
            with_latency = self.app.config.get("scan_latency", False)
            ping_first = self.app.config.get("scan_ping", False)
            if ping_first:
                from coolbox.utils import async_filter_active_hosts
                alive = asyncio.run(
                    async_filter_active_hosts(
                        [host],
                        concurrency=self.app.config.get("scan_ping_concurrency", 100),
                        timeout=self.app.config.get("scan_ping_timeout", 1.0),
                    )
                )
                if not alive:
                    self.app.window.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Port Scanner", f"{host} did not respond to ping"
                        ),
                    )
                    return
            from coolbox.utils import async_scan_ports, async_scan_port_list

            open_ports: "PortResult"
            if start_end:
                s, e = start_end
                open_ports = asyncio.run(
                    async_scan_ports(
                        host,
                        s,
                        e,
                        progress,
                        concurrency=concurrency,
                        cache_ttl=ttl,
                        timeout=timeout,
                        family=fam,
                        with_services=with_services,
                        with_banner=with_banner,
                        with_latency=with_latency,
                    )
                )
            else:
                open_ports = asyncio.run(
                    async_scan_port_list(
                        host,
                        ports,
                        progress,
                        concurrency=concurrency,
                        cache_ttl=ttl,
                        timeout=timeout,
                        family=fam,
                        with_services=with_services,
                        with_banner=with_banner,
                        with_latency=with_latency,
                    )
                )

            def show_result() -> None:
                if not open_ports:
                    if is_top:
                        msg = (
                            f"No open ports found on {host} in top {len(ports)} ports"
                        )
                    elif start_end:
                        s, e = start_end
                        msg = f"No open ports found on {host} in range {s}-{e}"
                    else:
                        msg = f"No open ports found on {host}"
                    messagebox.showinfo("Port Scanner", msg)
                    return
                if with_banner and isinstance(open_ports, dict):
                    banner_ports = cast(dict[int, "PortInfo"], open_ports)
                    ports_str = ", ".join(
                        f"{p}({info.service}:{info.banner or ''})"
                        for p, info in banner_ports.items()
                    )
                elif with_services and isinstance(open_ports, dict):
                    service_ports = cast(dict[int, str], open_ports)
                    ports_str = ", ".join(
                        f"{p}({svc})" for p, svc in service_ports.items()
                    )
                elif with_latency and isinstance(open_ports, dict):
                    latency_ports = cast(dict[int, "PortInfo"], open_ports)
                    ports_str = ", ".join(
                        f"{p}({info.latency * 1000:.1f}ms)" if info.latency is not None else str(p)
                        for p, info in latency_ports.items()
                    )
                else:
                    ports_str = ", ".join(str(p) for p in open_ports)
                messagebox.showinfo(
                    "Port Scanner",
                    f"Open ports on {host}: {ports_str}",
                )

            self.app.window.after(0, show_result)

        threading.Thread(target=run_scan, daemon=True).start()

    def _network_scan(self) -> None:
        """Scan multiple hosts for open ports."""
        hosts_raw = simpledialog.askstring(
            "Network Scanner", "Hosts (comma separated)", parent=self
        )
        if not hosts_raw:
            return
        from coolbox.utils import parse_hosts
        hosts = parse_hosts(hosts_raw)
        if not hosts:
            return

        rng = simpledialog.askstring(
            "Network Scanner",
            "Port or range (22, 20-25, ssh,http, 20-30:2, top100)",
            parent=self,
        )
        if not rng:
            return

        from coolbox.utils import parse_ports, ports_as_range
        try:
            ports = parse_ports(rng)
        except Exception:
            messagebox.showerror("Network Scanner", "Invalid port specification")
            return
        start_end = ports_as_range(ports)

        from coolbox.utils import (
            async_scan_targets,
            async_scan_targets_list,
            async_filter_active_hosts,
        )
        import threading
        import asyncio

        def progress(value: float | None) -> None:
            if value is None:
                if self.app.status_bar is not None:
                    self.app.window.after(0, self.app.status_bar.hide_progress)
            else:
                if self.app.status_bar is not None:
                    self.app.window.after(
                        0, lambda: self.app.status_bar.show_progress(value)
                    )

        def run_scan() -> None:
            ttl = self.app.config.get("scan_cache_ttl", 300)
            concurrency = self.app.config.get("scan_concurrency", 100)
            timeout = self.app.config.get("scan_timeout", 0.5)
            fam_opt = self.app.config.get("scan_family", "auto").lower()
            fam = None
            if fam_opt == "ipv4":
                fam = socket.AF_INET
            elif fam_opt == "ipv6":
                fam = socket.AF_INET6
            with_services = self.app.config.get("scan_services", False)
            with_banner = self.app.config.get("scan_banner", False)
            with_latency = self.app.config.get("scan_latency", False)
            ping_first = self.app.config.get("scan_ping", False)
            scan_prog: ProgressCallback
            if ping_first:
                def ping_prog(val: float | None) -> None:
                    if val is None:
                        progress(0.5)
                    else:
                        progress(val * 0.5)

                pinged = asyncio.run(
                    async_filter_active_hosts(
                        hosts,
                        ping_prog,
                        concurrency=self.app.config.get("scan_ping_concurrency", concurrency),
                        timeout=self.app.config.get("scan_ping_timeout", timeout),
                    )
                )
                hosts_to_scan = pinged
                if not hosts_to_scan:
                    self.app.window.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Network Scanner", "No hosts responded to ping"
                        ),
                    )
                    return

                def scan_prog_inner(val: float | None) -> None:
                    if val is None:
                        progress(1.0)
                    else:
                        progress(0.5 + val * 0.5)
                scan_prog = scan_prog_inner
            else:
                hosts_to_scan = hosts
                scan_prog = progress

            results: dict[str, "PortResult"]
            if start_end:
                s, e = start_end
                results = asyncio.run(
                    async_scan_targets(
                        hosts_to_scan,
                        s,
                        e,
                        scan_prog,
                        concurrency=concurrency,
                        cache_ttl=ttl,
                        timeout=timeout,
                        family=fam,
                        with_services=with_services,
                        with_banner=with_banner,
                        with_latency=with_latency,
                    )
                )
            else:
                results = asyncio.run(
                    async_scan_targets_list(
                        hosts_to_scan,
                        ports,
                        scan_prog,
                        concurrency=concurrency,
                        cache_ttl=ttl,
                        timeout=timeout,
                        family=fam,
                        with_services=with_services,
                        with_banner=with_banner,
                        with_latency=with_latency,
                    )
                )

            def show_result() -> None:
                lines = []
                for host, ports in results.items():
                    if not ports:
                        lines.append(f"{host}: none")
                        continue
                    if with_banner and isinstance(ports, dict):
                        banner_ports = cast(dict[int, "PortInfo"], ports)
                        ports_str = ", ".join(
                            f"{p}({info.service}:{info.banner or ''})"
                            for p, info in banner_ports.items()
                        )
                    elif with_services and isinstance(ports, dict):
                        service_ports = cast(dict[int, str], ports)
                        ports_str = ", ".join(
                            f"{p}({svc})" for p, svc in service_ports.items()
                        )
                    elif with_latency and isinstance(ports, dict):
                        latency_ports = cast(dict[int, "PortInfo"], ports)
                        ports_str = ", ".join(
                            f"{p}({info.latency * 1000:.1f}ms)" if info.latency is not None else str(p)
                            for p, info in latency_ports.items()
                        )
                    else:
                        ports_str = ", ".join(str(p) for p in ports)
                    lines.append(f"{host}: {ports_str}")
                messagebox.showinfo(
                    "Network Scanner", "\n".join(lines)
                )

            self.app.window.after(0, show_result)

        threading.Thread(target=run_scan, daemon=True).start()

    def _auto_network_scan(self) -> None:
        """Open the Auto Network Scan dialog."""
        from ..dialogs.auto_scan import AutoNetworkScanDialog

        AutoNetworkScanDialog(self.app)

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
