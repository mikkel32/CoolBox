"""
Tools view - Various utilities and tools
"""
import customtkinter as ctk
from tkinter import messagebox, simpledialog
import socket
import subprocess
import platform
import webbrowser


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
        """Launch batch rename tool"""
        self.app.status_bar.set_message("Launching Batch Rename tool...", "info")
        messagebox.showinfo("Batch Rename", "Batch rename tool would open here")

    def _file_converter(self):
        """Launch file converter"""
        self.app.status_bar.set_message("Launching File Converter...", "info")
        messagebox.showinfo("File Converter", "File converter tool would open here")

    def _duplicate_finder(self):
        """Launch duplicate finder"""
        self.app.status_bar.set_message("Launching Duplicate Finder...", "info")
        messagebox.showinfo("Duplicate Finder", "Duplicate finder would scan here")

    def _file_splitter(self):
        """Launch file splitter"""
        self.app.status_bar.set_message("Launching File Splitter...", "info")
        messagebox.showinfo("File Splitter", "File splitter tool would open here")

    def _system_info(self):
        """Show system information"""
        info = f"""System Information:
        
Platform: {platform.system()} {platform.release()}
Processor: {platform.processor()}
Architecture: {platform.architecture()[0]}
Python: {platform.python_version()}
"""
        messagebox.showinfo("System Info", info)

    def _process_manager(self):
        """Launch process manager"""
        self.app.status_bar.set_message("Opening Process Manager...", "info")

        if platform.system() == "Windows":
            subprocess.Popen("taskmgr")
        elif platform.system() == "Darwin":  # macOS
            subprocess.Popen(["open", "-a", "Activity Monitor"])
        else:  # Linux
            subprocess.Popen(["gnome-system-monitor"])

    def _disk_cleanup(self):
        """Launch disk cleanup"""
        self.app.status_bar.set_message("Launching Disk Cleanup...", "info")
        messagebox.showinfo("Disk Cleanup", "Disk cleanup would run here")

    def _registry_editor(self):
        """Launch registry editor"""
        if platform.system() == "Windows":
            self.app.status_bar.set_message("Opening Registry Editor...", "info")
            subprocess.Popen("regedit")
        else:
            self.app.status_bar.set_message("Registry Editor is Windows only", "warning")

    def _text_editor(self):
        """Launch text editor"""
        self.app.status_bar.set_message("Opening Text Editor...", "info")
        messagebox.showinfo("Text Editor", "Advanced text editor would open here")

    def _regex_tester(self):
        """Launch regex tester"""
        self.app.status_bar.set_message("Opening Regex Tester...", "info")
        messagebox.showinfo("Regex Tester", "Regex testing tool would open here")

    def _json_formatter(self):
        """Launch JSON formatter"""
        self.app.status_bar.set_message("Opening JSON Formatter...", "info")
        messagebox.showinfo("JSON Formatter", "JSON formatter would open here")

    def _base64_tool(self):
        """Launch Base64 tool"""
        self.app.status_bar.set_message("Opening Base64 Tool...", "info")
        messagebox.showinfo("Base64 Tool", "Base64 encoder/decoder would open here")

    def _ping_tool(self):
        """Launch ping tool"""
        host = simpledialog.askstring("Ping", "Enter host to ping", parent=self)
        if not host:
            return
        self.app.status_bar.set_message(f"Pinging {host}...", "info")
        count_flag = "-n" if platform.system() == "Windows" else "-c"
        try:
            result = subprocess.run(["ping", count_flag, "4", host], capture_output=True, text=True, timeout=10)
            messagebox.showinfo("Ping Result", result.stdout or result.stderr)
        except Exception as exc:
            messagebox.showerror("Ping Error", str(exc))

    def _port_scanner(self):
        """Launch port scanner"""
        host = simpledialog.askstring("Port Scanner", "Host", parent=self)
        port = simpledialog.askinteger("Port Scanner", "Port", parent=self, minvalue=1, maxvalue=65535)
        if not host or not port:
            return
        self.app.status_bar.set_message(f"Scanning {host}:{port}...", "info")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            try:
                sock.connect((host, port))
                messagebox.showinfo("Port Scanner", f"Port {port} is OPEN")
            except Exception:
                messagebox.showinfo("Port Scanner", f"Port {port} is CLOSED")

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
        self.app.status_bar.set_message("Opening Speed Test...", "info")
        webbrowser.open("https://fast.com")
