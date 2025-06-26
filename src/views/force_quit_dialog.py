"""Force Quit dialog for terminating processes."""

from __future__ import annotations

import os
import signal
import subprocess
import shutil

import re
import time
import socket
from tkinter import messagebox

import customtkinter as ctk
import psutil


class ForceQuitDialog(ctk.CTkToplevel):
    """Dialog showing running processes that can be terminated."""

    def __init__(self, app):
        super().__init__(app.window)
        self.app = app
        self.title("Force Quit")
        self.resizable(False, False)
        self.geometry("500x400")
        self._after_id: int | None = None
        self.pid_vars: dict[int, ctk.IntVar] = {}

        ctk.CTkLabel(
            self,
            text="Force Quit Running Processes",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(pady=10)

        search_frame = ctk.CTkFrame(self, fg_color="transparent")
        search_frame.pack(fill="x", padx=10)
        self.search_var = ctk.StringVar()
        entry = ctk.CTkEntry(search_frame, textvariable=self.search_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<KeyRelease>", lambda _e: self._populate())

        self.sort_var = ctk.StringVar(value="CPU")
        sort_menu = ctk.CTkOptionMenu(
            search_frame,
            variable=self.sort_var,
            values=["CPU", "Memory", "PID"],
            command=lambda _v: self._populate(),
        )
        sort_menu.pack(side="left", padx=5)
        ctk.CTkButton(search_frame, text="Refresh", command=self._populate).pack(
            side="left", padx=5
        )
        ctk.CTkButton(
            search_frame, text="Kill by Name", command=self._kill_by_name
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill by Pattern",
            command=self._kill_by_pattern,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill by Port",
            command=self._kill_by_port,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill by Host",
            command=self._kill_by_host,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill by File",
            command=self._kill_by_file,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill by Exec",
            command=self._kill_by_executable,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill by User",
            command=self._kill_by_user,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill by Cmdline",
            command=self._kill_by_cmdline,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill High CPU",
            command=self._kill_high_cpu,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill High Mem",
            command=self._kill_high_memory,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill by Parent",
            command=self._kill_by_parent,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill Children",
            command=self._kill_children,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill by Age",
            command=self._kill_by_age,
        ).pack(side="left", padx=5)

        self.list_frame = ctk.CTkScrollableFrame(self)
        self.list_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.list_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            self, text="Force Quit Selected", command=self._kill_selected
        ).pack(pady=(5, 0))

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._auto_refresh()

    @staticmethod
    def force_kill(pid: int) -> None:
        """Forcefully kill a PID using platform specific fallbacks."""
        try:
            proc = psutil.Process(pid)
            proc.kill()
            try:
                proc.wait(timeout=3)
            except (psutil.TimeoutExpired, ChildProcessError):
                pass
            return
        except (psutil.NoSuchProcess, PermissionError, psutil.AccessDenied):
            pass
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=False)
        else:
            os.kill(pid, signal.SIGKILL)

    @classmethod
    def force_kill_multiple(cls, pids: list[int]) -> int:
        """Kill multiple PIDs, returning number successfully killed."""
        count = 0
        for pid in pids:
            try:
                cls.force_kill(pid)
                count += 1
            except Exception:
                continue
        return count

    @classmethod
    def force_kill_by_name(cls, name: str) -> int:
        """Kill all processes with the given name. Returns number killed."""
        count = 0
        for proc in psutil.process_iter(["pid", "name"]):
            if proc.info.get("name", "").lower() == name.lower():
                try:
                    cls.force_kill(proc.pid)
                    count += 1
                except Exception:
                    pass
        return count

    @classmethod
    def force_kill_by_pattern(cls, regex: re.Pattern[str]) -> int:
        """Kill processes whose names match regex. Returns number killed."""
        count = 0
        for proc in psutil.process_iter(["pid", "name"]):
            name = proc.info.get("name", "")
            if regex.search(name):
                try:
                    cls.force_kill(proc.pid)
                    count += 1
                except Exception:
                    pass
        return count

    @classmethod
    def force_kill_by_port(cls, port: int) -> int:
        """Kill processes that have an open connection on the given port."""
        pids: set[int] = set()
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port:
                if conn.pid:
                    pids.add(conn.pid)
            if conn.raddr and conn.raddr.port == port:
                if conn.pid:
                    pids.add(conn.pid)
        return cls.force_kill_multiple(list(pids))

    @classmethod
    def force_kill_by_host(cls, host: str) -> int:
        """Kill processes connected to the given remote host."""
        try:
            ip = socket.gethostbyname(host)
        except Exception:
            ip = host
        pids: set[int] = set()
        for conn in psutil.net_connections(kind="inet"):
            if conn.raddr and conn.raddr.ip == ip:
                if conn.pid:
                    pids.add(conn.pid)
        return cls.force_kill_multiple(list(pids))

    @classmethod
    def force_kill_by_file(cls, path: str) -> int:
        """Kill processes that have the specified file open."""
        count = 0
        target = os.path.abspath(path)
        lsof = shutil.which("lsof")
        if lsof:
            result = subprocess.run([lsof, "-t", target], capture_output=True, text=True)
            for line in result.stdout.splitlines():
                try:
                    pid = int(line.strip())
                except ValueError:
                    continue
                try:
                    cls.force_kill(pid)
                    count += 1
                except Exception:
                    pass
            if count:
                return count
        for proc in psutil.process_iter(["pid"]):
            try:
                files = proc.open_files()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            for f in files:
                try:
                    if os.path.abspath(f.path) == target:
                        cls.force_kill(proc.pid)
                        count += 1
                        break
                except Exception:
                    continue
        return count

    @staticmethod
    def terminate_tree(pid: int, timeout: float = 3.0) -> None:
        """Gracefully terminate a process and its children."""
        try:
            root = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return
        children = root.children(recursive=True)
        for p in [root, *children]:
            try:
                p.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        _, alive = psutil.wait_procs([root, *children], timeout=timeout)
        for p in alive:
            try:
                ForceQuitDialog.force_kill(p.pid)
            except Exception:
                pass

    @classmethod
    def force_kill_by_executable(
        cls, regex: re.Pattern[str], *, exclude_self: bool = True
    ) -> int:
        """Kill processes whose executable path matches regex."""
        count = 0
        self_pid = os.getpid() if exclude_self else None
        for proc in psutil.process_iter(["pid", "exe"]):
            if exclude_self and proc.pid == self_pid:
                continue
            exe = proc.info.get("exe") or ""
            if exe and regex.search(exe):
                try:
                    cls.force_kill(proc.pid)
                    count += 1
                except Exception:
                    pass
        return count

    @classmethod
    def force_kill_by_user(
        cls,
        username: str,
        *,
        exe_regex: re.Pattern[str] | None = None,
        exclude_self: bool = True,
    ) -> int:
        """Kill processes for a user optionally filtered by executable regex."""
        count = 0
        self_pid = os.getpid() if exclude_self else None
        for proc in psutil.process_iter(["pid", "username", "exe"]):
            if exclude_self and proc.pid == self_pid:
                continue
            user = proc.info.get("username")
            if not user or user.lower() != username.lower():
                continue
            if exe_regex is not None:
                exe = proc.info.get("exe") or ""
                if not exe_regex.search(exe):
                    continue
            try:
                cls.force_kill(proc.pid)
                count += 1
            except Exception:
                pass
        return count

    @classmethod
    def force_kill_by_cmdline(cls, regex: re.Pattern[str]) -> int:
        """Kill processes whose command line matches regex."""
        count = 0
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmd = " ".join(proc.info.get("cmdline") or [])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if regex.search(cmd):
                try:
                    cls.force_kill(proc.pid)
                    count += 1
                except Exception:
                    pass
        return count

    @classmethod
    def force_kill_above_cpu(cls, threshold: float) -> int:
        """Kill processes using more CPU percent than threshold."""
        count = 0
        for proc in psutil.process_iter(["pid"]):
            try:
                if proc.cpu_percent(interval=0.1) > threshold:
                    cls.force_kill(proc.pid)
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return count

    @classmethod
    def force_kill_above_memory(cls, threshold_mb: float) -> int:
        """Kill processes using more memory (MB) than threshold."""
        count = 0
        for proc in psutil.process_iter(["pid", "memory_info"]):
            try:
                mem_mb = proc.info["memory_info"].rss / (1024 * 1024)
                if mem_mb > threshold_mb:
                    cls.force_kill(proc.pid)
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
        return count

    @classmethod
    def force_kill_by_parent(
        cls, parent_pid: int, *, include_parent: bool = False
    ) -> int:
        """Kill processes by parent PID."""
        count = 0
        try:
            parent = psutil.Process(parent_pid)
        except psutil.NoSuchProcess:
            return 0
        procs = parent.children(recursive=True)
        if include_parent:
            procs.append(parent)
        for proc in procs:
            try:
                cls.force_kill(proc.pid)
                count += 1
            except Exception:
                pass
        return count

    @classmethod
    def force_kill_children(cls, parent_pid: int) -> int:
        """Kill only the children of a process."""
        return cls.force_kill_by_parent(parent_pid, include_parent=False)

    @classmethod
    def force_kill_older_than(
        cls, seconds: float, cmd_regex: re.Pattern[str] | None = None
    ) -> int:
        """Kill processes older than ``seconds`` optionally filtered by command line."""
        count = 0
        now = time.time()
        for proc in psutil.process_iter(["pid", "create_time", "cmdline"]):
            try:
                if proc.pid == os.getpid() or now - proc.info["create_time"] <= seconds:
                    continue
                if cmd_regex is not None:
                    cmd = " ".join(proc.info.get("cmdline") or [])
                    if not cmd_regex.search(cmd):
                        continue
                cls.force_kill(proc.pid)
                count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
        return count

    def _populate(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        self.pid_vars.clear()
        query = self.search_var.get().lower()
        processes = list(
            psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"])
        )
        key_func = {
            "CPU": lambda p: p.info.get("cpu_percent", 0.0),
            "Memory": lambda p: p.info.get("memory_info").rss,
            "PID": lambda p: p.info.get("pid"),
        }.get(self.sort_var.get(), lambda p: p.info.get("cpu_percent", 0.0))
        processes.sort(key=key_func, reverse=True)
        for proc in processes:
            name = proc.info.get("name", "")
            if query and query not in name.lower():
                continue
            pid = proc.info["pid"]
            cpu = proc.info.get("cpu_percent", 0.0)
            mem = proc.info.get("memory_info").rss / (1024 * 1024)
            row = ctk.CTkFrame(self.list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            label = ctk.CTkLabel(
                row,
                text=f"{pid:6d} {name:<25} {cpu:5.1f}% {mem:8.1f}MB",
                anchor="w",
            )
            label.pack(side="left", fill="x", expand=True)
            label.bind(
                "<Double-Button-1>",
                lambda _e, p=pid: self._confirm_kill(p),
            )
            var = ctk.IntVar(value=0)
            self.pid_vars[pid] = var
            ctk.CTkCheckBox(row, variable=var, width=15, text="").pack(side="right")

    def _kill_selected(self) -> None:
        pids = [pid for pid, var in self.pid_vars.items() if var.get()]
        if not pids:
            messagebox.showerror("Force Quit", "No process selected", parent=self)
            return
        if not messagebox.askyesno(
            "Force Quit", f"Force terminate {len(pids)} process(es)?", parent=self
        ):
            return
        errors: list[str] = []
        for pid in pids:
            try:
                self.terminate_tree(pid)
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            messagebox.showerror("Force Quit", "\n".join(errors), parent=self)
        else:
            messagebox.showinfo(
                "Force Quit", f"Terminated {len(pids)} process(es)", parent=self
            )
        self._populate()

    def _confirm_kill(self, pid: int) -> None:
        if messagebox.askyesno("Force Quit", f"Terminate PID {pid}?", parent=self):
            try:
                self.terminate_tree(pid)
                self._populate()
            except Exception as exc:
                messagebox.showerror("Force Quit", str(exc), parent=self)

    def _kill_by_name(self) -> None:
        name = self.search_var.get().strip()
        if not name:
            messagebox.showerror("Force Quit", "Enter a process name", parent=self)
            return
        count = self.force_kill_by_name(name)
        messagebox.showinfo(
            "Force Quit", f"Terminated {count} process(es) named {name}", parent=self
        )
        self._populate()

    def _kill_by_pattern(self) -> None:
        pattern = self.search_var.get().strip()
        if not pattern:
            messagebox.showerror("Force Quit", "Enter a regex pattern", parent=self)
            return
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            messagebox.showerror("Force Quit", str(exc), parent=self)
            return
        count = self.force_kill_by_pattern(regex)
        messagebox.showinfo(
            "Force Quit", f"Terminated {count} matching process(es)", parent=self
        )
        self._populate()

    def _kill_by_port(self) -> None:
        value = self.search_var.get().strip()
        if not value.isdigit():
            messagebox.showerror("Force Quit", "Enter a numeric port", parent=self)
            return
        port = int(value)
        count = self.force_kill_by_port(port)
        messagebox.showinfo(
            "Force Quit", f"Terminated {count} process(es) using port {port}", parent=self
        )
        self._populate()

    def _kill_by_host(self) -> None:
        host = self.search_var.get().strip()
        if not host:
            messagebox.showerror("Force Quit", "Enter a hostname or IP", parent=self)
            return
        count = self.force_kill_by_host(host)
        messagebox.showinfo(
            "Force Quit", f"Terminated {count} process(es) connected to {host}", parent=self
        )
        self._populate()

    def _kill_by_file(self) -> None:
        path = self.search_var.get().strip()
        if not path:
            messagebox.showerror("Force Quit", "Enter a file path", parent=self)
            return
        count = self.force_kill_by_file(path)
        messagebox.showinfo(
            "Force Quit", f"Terminated {count} process(es) using {path}", parent=self
        )
        self._populate()

    def _kill_by_executable(self) -> None:
        pattern = self.search_var.get().strip()
        if not pattern:
            messagebox.showerror("Force Quit", "Enter an executable regex", parent=self)
            return
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            messagebox.showerror("Force Quit", str(exc), parent=self)
            return
        count = self.force_kill_by_executable(regex)
        messagebox.showinfo(
            "Force Quit", f"Terminated {count} matching process(es)", parent=self
        )
        self._populate()

    def _kill_by_user(self) -> None:
        username = self.search_var.get().strip()
        if not username:
            messagebox.showerror("Force Quit", "Enter a username", parent=self)
            return
        count = self.force_kill_by_user(username)
        messagebox.showinfo(
            "Force Quit", f"Terminated {count} process(es) for {username}", parent=self
        )
        self._populate()

    def _kill_by_cmdline(self) -> None:
        pattern = self.search_var.get().strip()
        if not pattern:
            messagebox.showerror("Force Quit", "Enter a command line regex", parent=self)
            return
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            messagebox.showerror("Force Quit", str(exc), parent=self)
            return
        count = self.force_kill_by_cmdline(regex)
        messagebox.showinfo(
            "Force Quit",
            f"Terminated {count} matching process(es)",
            parent=self,
        )
        self._populate()

    def _kill_high_cpu(self) -> None:
        value = self.search_var.get().strip()
        try:
            threshold = float(value)
        except ValueError:
            messagebox.showerror("Force Quit", "Enter CPU threshold", parent=self)
            return
        count = self.force_kill_above_cpu(threshold)
        messagebox.showinfo(
            "Force Quit", f"Terminated {count} process(es) above {threshold}% CPU", parent=self
        )
        self._populate()

    def _kill_high_memory(self) -> None:
        value = self.search_var.get().strip()
        try:
            threshold = float(value)
        except ValueError:
            messagebox.showerror("Force Quit", "Enter memory threshold MB", parent=self)
            return
        count = self.force_kill_above_memory(threshold)
        messagebox.showinfo(
            "Force Quit",
            f"Terminated {count} process(es) above {threshold}MB",
            parent=self,
        )
        self._populate()

    def _kill_by_parent(self) -> None:
        value = self.search_var.get().strip()
        if not value.isdigit():
            messagebox.showerror("Force Quit", "Enter a parent PID", parent=self)
            return
        pid = int(value)
        count = self.force_kill_by_parent(pid, include_parent=True)
        messagebox.showinfo(
            "Force Quit",
            f"Terminated {count} process(es) related to PID {pid}",
            parent=self,
        )
        self._populate()

    def _kill_children(self) -> None:
        value = self.search_var.get().strip()
        if not value.isdigit():
            messagebox.showerror("Force Quit", "Enter a parent PID", parent=self)
            return
        pid = int(value)
        count = self.force_kill_children(pid)
        messagebox.showinfo(
            "Force Quit",
            f"Terminated {count} child process(es) of {pid}",
            parent=self,
        )
        self._populate()

    def _kill_by_age(self) -> None:
        value = self.search_var.get().strip()
        try:
            seconds = float(value)
        except ValueError:
            messagebox.showerror("Force Quit", "Enter age in seconds", parent=self)
            return
        count = self.force_kill_older_than(seconds)
        messagebox.showinfo(
            "Force Quit",
            f"Terminated {count} process(es) older than {seconds}s",
            parent=self,
        )
        self._populate()

    def _auto_refresh(self) -> None:
        if not self.winfo_exists():
            return
        self._populate()
        self._after_id = self.after(3000, self._auto_refresh)

    def _on_close(self) -> None:
        if self._after_id is not None:
            self.after_cancel(self._after_id)
        self.destroy()
