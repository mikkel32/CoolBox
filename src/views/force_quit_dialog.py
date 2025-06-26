"""Force Quit dialog for terminating processes."""

from __future__ import annotations

import os
import signal
import subprocess
import shutil

import re
import time
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from dataclasses import dataclass, field
from tkinter import messagebox, filedialog

import customtkinter as ctk
import psutil


@dataclass(slots=True)
class ProcessEntry:
    """Snapshot of a running process."""

    pid: int
    name: str
    cpu: float
    mem: float
    user: str
    start: float
    status: str
    cpu_time: float
    threads: int
    read_bytes: int
    write_bytes: int
    files: int
    conns: int
    io_rate: float = 0.0
    samples: list[float] = field(default_factory=list)
    io_samples: list[float] = field(default_factory=list)

    def add_sample(self, cpu: float, io: float) -> None:
        self.samples.append(cpu)
        self.io_samples.append(io)
        if len(self.samples) > 5:
            self.samples.pop(0)
        if len(self.io_samples) > 5:
            self.io_samples.pop(0)

    @property
    def avg_cpu(self) -> float:
        if not self.samples:
            return self.cpu
        return sum(self.samples) / len(self.samples)

    @property
    def avg_io(self) -> float:
        if not self.io_samples:
            return self.io_rate
        return sum(self.io_samples) / len(self.io_samples)

    def changed_since(self, other: "ProcessEntry") -> bool:
        return any(
            [
                self.name != other.name,
                self.user != other.user,
                self.mem != other.mem,
                self.status != other.status,
                abs(self.cpu - other.cpu) > 0.1,
                self.threads != other.threads,
                abs(self.io_rate - other.io_rate) > 0.1,
                self.files != other.files,
                self.conns != other.conns,
            ]
        )


class ProcessWatcher(threading.Thread):
    """Background thread that continually gathers process information."""

    def __init__(self, queue: Queue[tuple[dict[int, ProcessEntry], set[int]]], interval: float = 2.0, detail_interval: int = 3) -> None:
        super().__init__(daemon=True)
        self.queue = queue
        self.interval = interval
        self.detail_interval = max(1, detail_interval)
        self._stop_event = threading.Event()
        self._snapshot: dict[int, ProcessEntry] = {}
        self._last_ts = time.monotonic()
        self._tick = 0

    def set_interval(self, interval: float) -> None:
        self.interval = max(0.5, float(interval))

    def run(self) -> None:
        while not self._stop_event.is_set():
            now = time.monotonic()
            delta = max(now - self._last_ts, 0.001)
            self._last_ts = now
            self._tick += 1
            updates: dict[int, ProcessEntry] = {}
            current: set[int] = set()
            procs = list(
                psutil.process_iter(
                    [
                        "pid",
                        "name",
                        "username",
                        "create_time",
                        "memory_info",
                        "status",
                        "cpu_times",
                        "num_threads",
                    ]
                )
            )

            detail = self._tick % self.detail_interval == 0

            def collect(proc: psutil.Process) -> ProcessEntry | None:
                try:
                    with proc.oneshot():
                        pid = proc.info["pid"]
                        name = proc.info.get("name", "")
                        user = proc.info.get("username") or ""
                        mem = proc.info["memory_info"].rss / (1024 * 1024)
                        cpu_time = sum(proc.info.get("cpu_times"))
                        start = proc.info.get("create_time", 0.0)
                        status = proc.info.get("status", "")
                        threads = proc.info.get("num_threads", 0)
                        prev_entry = self._snapshot.get(pid)
                        try:
                            io = proc.io_counters()
                            read_bytes = io.read_bytes
                            write_bytes = io.write_bytes
                        except Exception:
                            read_bytes = write_bytes = 0
                        if detail:
                            try:
                                if hasattr(proc, "num_handles"):
                                    files = proc.num_handles()
                                elif hasattr(proc, "num_fds"):
                                    files = proc.num_fds()
                                else:
                                    files = len(proc.open_files())
                            except Exception:
                                files = prev_entry.files if prev_entry else 0
                            try:
                                conns = len(proc.connections(kind="inet"))
                            except Exception:
                                conns = prev_entry.conns if prev_entry else 0
                        else:
                            files = prev_entry.files if prev_entry else 0
                            conns = prev_entry.conns if prev_entry else 0
                except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                    return None

                prev = self._snapshot.get(pid)
                if prev is None:
                    cpu = 0.0
                    samples: list[float] = []
                    io_rate = 0.0
                else:
                    cpu = (cpu_time - prev.cpu_time) / delta / psutil.cpu_count() * 100
                    samples = prev.samples
                    io_rate = (
                        (read_bytes - prev.read_bytes + write_bytes - prev.write_bytes)
                        / delta
                        / (1024 * 1024)
                    )

                entry = ProcessEntry(
                    pid=pid,
                    name=name,
                    cpu=round(cpu, 1),
                    mem=round(mem, 1),
                    user=user,
                    start=start,
                    status=status,
                    cpu_time=cpu_time,
                    threads=threads,
                    read_bytes=read_bytes,
                    write_bytes=write_bytes,
                    files=files,
                    conns=conns,
                    io_rate=round(io_rate, 1),
                    samples=samples,
                )
                entry.add_sample(entry.cpu, entry.io_rate)
                return entry

            with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 1) * 2)) as ex:
                futures = {ex.submit(collect, p): p.info["pid"] for p in procs}
                for fut in as_completed(futures):
                    entry = fut.result()
                    if entry is None:
                        continue
                    pid = entry.pid
                    current.add(pid)
                    prev = self._snapshot.get(pid)
                    if prev is None or entry.changed_since(prev):
                        updates[pid] = entry
                    self._snapshot[pid] = entry
            removed = set(self._snapshot) - current
            if updates or removed:
                self.queue.put((updates, removed))
                for pid in removed:
                    self._snapshot.pop(pid, None)
            if self._stop_event.wait(self.interval):
                break

    def stop(self) -> None:
        self._stop_event.set()


class ForceQuitDialog(ctk.CTkToplevel):
    """Dialog showing running processes that can be terminated."""

    def __init__(self, app):
        super().__init__(app.window)
        self.app = app
        self.title("Force Quit")
        self.resizable(False, False)
        self.geometry("650x450")
        self._after_id: int | None = None
        self.pid_vars: dict[int, ctk.IntVar] = {}
        self._debounce_id: int | None = None
        self.process_snapshot: dict[int, ProcessEntry] = {}
        self.rows: dict[int, tuple[ctk.CTkFrame, ctk.CTkLabel, ctk.IntVar]] = {}
        self._queue: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
        self._watcher = ProcessWatcher(self._queue)
        self._watcher.start()
        self.after(0, self._auto_refresh)

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

        self.filter_var = ctk.StringVar(value="Name")
        filter_menu = ctk.CTkOptionMenu(
            search_frame,
            variable=self.filter_var,
            values=[
                "Name",
                "User",
                "PID",
                "CPU ≥",
                "Avg CPU ≥",
                "Memory ≥",
                "Threads ≥",
                "Age ≥",
                "IO ≥",
                "Avg IO ≥",
                "Files ≥",
                "Conns ≥",
                "Status",
            ],
            command=lambda _v: self._populate(),
        )
        filter_menu.pack(side="left", padx=5)

        self.sort_var = ctk.StringVar(value="CPU")
        sort_menu = ctk.CTkOptionMenu(
            search_frame,
            variable=self.sort_var,
            values=[
                "CPU",
                "Avg CPU",
                "Memory",
                "Threads",
                "IO",
                "Avg IO",
                "Files",
                "Conns",
                "PID",
                "User",
                "Start",
                "Age",
            ],
            command=lambda _v: self._populate(),
        )
        sort_menu.pack(side="left", padx=5)

        self.interval_var = ctk.StringVar(value="2")
        interval_menu = ctk.CTkOptionMenu(
            search_frame,
            variable=self.interval_var,
            values=["1", "2", "5"],
            command=lambda v: self._watcher.set_interval(float(v)),
        )
        interval_menu.pack(side="left", padx=5)
        ctk.CTkButton(search_frame, text="Refresh", command=self._populate).pack(
            side="left", padx=5
        )
        ctk.CTkButton(search_frame, text="Save CSV", command=self._export_csv).pack(
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
            text="Kill High IO",
            command=self._kill_high_io,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill CPU Avg",
            command=self._kill_high_cpu_avg,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill Many Threads",
            command=self._kill_high_threads,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill Many Files",
            command=self._kill_high_files,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            search_frame,
            text="Kill Many Conns",
            command=self._kill_high_conns,
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
        ctk.CTkButton(
            search_frame,
            text="Kill Zombies",
            command=self._kill_zombies,
        ).pack(side="left", padx=5)

        self.list_frame = ctk.CTkScrollableFrame(self)
        self.list_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.list_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            self, text="Force Quit Selected", command=self._kill_selected
        ).pack(pady=(5, 0))

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._auto_refresh()

    def _drain_queue(self) -> None:
        while not self._queue.empty():
            updates, removed = self._queue.get_nowait()
            self.process_snapshot.update(updates)
            for pid in removed:
                self.process_snapshot.pop(pid, None)

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
    def force_kill_above_threads(cls, threshold: int) -> int:
        """Kill processes with thread count greater than threshold."""
        count = 0
        for proc in psutil.process_iter(["pid", "num_threads"]):
            try:
                if proc.info.get("num_threads", 0) > threshold:
                    cls.force_kill(proc.pid)
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
        return count

    @classmethod
    def force_kill_above_io(
        cls, threshold_mb: float, interval: float = 1.0
    ) -> int:
        """Kill processes with I/O rate greater than threshold."""
        snapshot: dict[int, int] = {}
        for proc in psutil.process_iter(["pid"]):
            try:
                io = proc.io_counters()
                snapshot[proc.pid] = io.read_bytes + io.write_bytes
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue
        time.sleep(interval)
        count = 0
        for proc in psutil.process_iter(["pid"]):
            try:
                io = proc.io_counters()
                prev = snapshot.get(proc.pid)
                if prev is None:
                    continue
                rate = (
                    io.read_bytes
                    + io.write_bytes
                    - prev
                ) / interval / (1024 * 1024)
                if rate > threshold_mb:
                    cls.force_kill(proc.pid)
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue
        return count

    @classmethod
    def force_kill_above_files(cls, threshold: int) -> int:
        """Kill processes with more open files than ``threshold``."""
        count = 0
        for proc in psutil.process_iter(["pid"]):
            try:
                if len(proc.open_files()) > threshold:
                    cls.force_kill(proc.pid)
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        return count

    @classmethod
    def force_kill_above_conns(cls, threshold: int) -> int:
        """Kill processes with more network connections than ``threshold``."""
        count = 0
        for proc in psutil.process_iter(["pid"]):
            try:
                if len(proc.connections(kind="inet")) > threshold:
                    cls.force_kill(proc.pid)
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return count

    @classmethod
    def force_kill_sustained_cpu(
        cls, threshold: float, duration: float = 1.0
    ) -> int:
        """Kill processes averaging above CPU ``threshold`` during ``duration``."""
        snapshot: dict[int, float] = {}
        for proc in psutil.process_iter(["pid", "cpu_times"]):
            try:
                snapshot[proc.pid] = sum(proc.cpu_times())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        time.sleep(duration)
        count = 0
        for proc in psutil.process_iter(["pid", "cpu_times"]):
            try:
                start = snapshot.get(proc.pid)
                if start is None:
                    continue
                cpu = (sum(proc.cpu_times()) - start) / duration / psutil.cpu_count() * 100
                if cpu > threshold:
                    cls.force_kill(proc.pid)
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
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

    @classmethod
    def force_kill_zombies(cls) -> int:
        """Terminate processes in a zombie state."""
        count = 0
        for proc in psutil.process_iter(["pid", "status"]):
            try:
                if proc.info.get("status") == psutil.STATUS_ZOMBIE:
                    cls.force_kill(proc.pid)
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
        return count

    def _populate(self) -> None:
        if self._debounce_id is not None:
            self.after_cancel(self._debounce_id)
        self._debounce_id = self.after(150, self._apply_filter_sort)

    def _apply_filter_sort(self) -> None:
        query = self.search_var.get().lower()
        sort_key = self.sort_var.get()
        filter_by = self.filter_var.get()

        processes = list(self.process_snapshot.values())
        if query:
            if filter_by == "Name":
                processes = [p for p in processes if query in p.name.lower()]
            elif filter_by == "User":
                processes = [p for p in processes if query in p.user.lower()]
            elif filter_by == "PID" and query.isdigit():
                pid_val = int(query)
                processes = [p for p in processes if p.pid == pid_val]
            elif filter_by == "CPU ≥":
                try:
                    threshold = float(query)
                except ValueError:
                    processes = []
                else:
                    processes = [p for p in processes if p.cpu >= threshold]
            elif filter_by == "Avg CPU ≥":
                try:
                    threshold = float(query)
                except ValueError:
                    processes = []
                else:
                    processes = [p for p in processes if p.avg_cpu >= threshold]
            elif filter_by == "Memory ≥":
                try:
                    threshold = float(query)
                except ValueError:
                    processes = []
                else:
                    processes = [p for p in processes if p.mem >= threshold]
            elif filter_by == "Threads ≥":
                try:
                    threshold = int(float(query))
                except ValueError:
                    processes = []
                else:
                    processes = [p for p in processes if p.threads >= threshold]
            elif filter_by == "Age ≥":
                try:
                    threshold = float(query)
                except ValueError:
                    processes = []
                else:
                    now = time.time()
                    processes = [p for p in processes if now - p.start >= threshold]
            elif filter_by == "IO ≥":
                try:
                    threshold = float(query)
                except ValueError:
                    processes = []
                else:
                    processes = [p for p in processes if p.io_rate >= threshold]
            elif filter_by == "Avg IO ≥":
                try:
                    threshold = float(query)
                except ValueError:
                    processes = []
                else:
                    processes = [p for p in processes if p.avg_io >= threshold]
            elif filter_by == "Files ≥":
                try:
                    threshold = int(float(query))
                except ValueError:
                    processes = []
                else:
                    processes = [p for p in processes if p.files >= threshold]
            elif filter_by == "Conns ≥":
                try:
                    threshold = int(float(query))
                except ValueError:
                    processes = []
                else:
                    processes = [p for p in processes if p.conns >= threshold]
            elif filter_by == "Status":
                processes = [p for p in processes if query in p.status.lower()]
            else:
                processes = []

        key_func = {
            "CPU": lambda p: p.cpu,
            "Avg CPU": lambda p: p.avg_cpu,
            "Memory": lambda p: p.mem,
            "Threads": lambda p: p.threads,
            "IO": lambda p: p.io_rate,
            "Avg IO": lambda p: p.avg_io,
            "Files": lambda p: p.files,
            "Conns": lambda p: p.conns,
            "PID": lambda p: p.pid,
            "User": lambda p: p.user.lower(),
            "Start": lambda p: p.start,
            "Age": lambda p: time.time() - p.start,
        }.get(sort_key, lambda p: p.cpu)
        processes.sort(key=key_func, reverse=True)
        self._update_list(processes)

    def _update_list(self, processes: list[ProcessEntry]) -> None:
        existing = set(self.rows)
        for entry in processes:
            pid = entry.pid
            age = time.time() - entry.start
            user_display = (entry.user or "")[:8]
            text = (
                f"{pid:6d} {user_display:<8} {entry.name:<25} "
                f"{entry.avg_cpu:5.1f}% {entry.mem:8.1f}MB "
                f"{entry.io_rate:5.1f}/{entry.avg_io:5.1f}MB/s "
                f"T{entry.threads:3d} F{entry.files:3d} C{entry.conns:3d} "
                f"{entry.status[:6]:<6} {age:7.1f}s"
            )
            if pid in self.rows:
                frame, label, var = self.rows[pid]
                label.configure(text=text)
                existing.remove(pid)
            else:
                frame = ctk.CTkFrame(self.list_frame, fg_color="transparent")
                label = ctk.CTkLabel(frame, text=text, anchor="w")
                label.pack(side="left", fill="x", expand=True)
                label.bind("<Double-Button-1>", lambda _e, p=pid: self._confirm_kill(p))
                var = ctk.IntVar(value=0)
                ctk.CTkCheckBox(frame, variable=var, width=15, text="").pack(side="right")
                frame.pack(fill="x", pady=2)
                self.pid_vars[pid] = var
                self.rows[pid] = (frame, label, var)
        for pid in existing:
            frame, _label, _var = self.rows.pop(pid)
            frame.destroy()
            self.pid_vars.pop(pid, None)

    def _export_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")],
            title="Save Process List",
        )
        if not path:
            return
        try:
            import csv

            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(
                    [
                        "pid",
                        "user",
                        "name",
                        "cpu",
                        "avg_cpu",
                        "mem",
                        "io_rate",
                        "avg_io",
                        "threads",
                        "files",
                        "conns",
                        "start",
                        "status",
                    ]
                )
                for entry in self.process_snapshot.values():
                    writer.writerow(
                        [
                            entry.pid,
                            entry.user or "",
                            entry.name,
                            entry.cpu,
                            f"{entry.avg_cpu:.1f}",
                            entry.mem,
                            entry.io_rate,
                            f"{entry.avg_io:.1f}",
                            entry.threads,
                            entry.files,
                            entry.conns,
                            entry.start,
                            entry.status,
                        ]
                    )
            messagebox.showinfo("Force Quit", f"Saved to {path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Force Quit", str(exc), parent=self)

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

    def _kill_high_io(self) -> None:
        value = self.search_var.get().strip()
        try:
            threshold = float(value)
        except ValueError:
            messagebox.showerror("Force Quit", "Enter IO threshold MB/s", parent=self)
            return
        count = self.force_kill_above_io(threshold)
        messagebox.showinfo(
            "Force Quit",
            f"Terminated {count} process(es) above {threshold}MB/s IO",
            parent=self,
        )
        self._populate()

    def _kill_high_cpu_avg(self) -> None:
        value = self.search_var.get().strip()
        try:
            threshold = float(value)
        except ValueError:
            messagebox.showerror("Force Quit", "Enter CPU threshold", parent=self)
            return
        count = self.force_kill_sustained_cpu(threshold)
        messagebox.showinfo(
            "Force Quit",
            f"Terminated {count} process(es) above {threshold}% avg CPU",
            parent=self,
        )
        self._populate()

    def _kill_high_threads(self) -> None:
        value = self.search_var.get().strip()
        try:
            threshold = int(float(value))
        except ValueError:
            messagebox.showerror("Force Quit", "Enter thread count", parent=self)
            return
        count = self.force_kill_above_threads(threshold)
        messagebox.showinfo(
            "Force Quit",
            f"Terminated {count} process(es) above {threshold} threads",
            parent=self,
        )
        self._populate()

    def _kill_high_files(self) -> None:
        value = self.search_var.get().strip()
        try:
            threshold = int(float(value))
        except ValueError:
            messagebox.showerror("Force Quit", "Enter file count", parent=self)
            return
        count = self.force_kill_above_files(threshold)
        messagebox.showinfo(
            "Force Quit",
            f"Terminated {count} process(es) above {threshold} files",
            parent=self,
        )
        self._populate()

    def _kill_high_conns(self) -> None:
        value = self.search_var.get().strip()
        try:
            threshold = int(float(value))
        except ValueError:
            messagebox.showerror("Force Quit", "Enter connection count", parent=self)
            return
        count = self.force_kill_above_conns(threshold)
        messagebox.showinfo(
            "Force Quit",
            f"Terminated {count} process(es) above {threshold} conns",
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

    def _kill_zombies(self) -> None:
        count = self.force_kill_zombies()
        messagebox.showinfo(
            "Force Quit",
            f"Terminated {count} zombie process(es)",
            parent=self,
        )
        self._populate()

    def _auto_refresh(self) -> None:
        if not self.winfo_exists():
            return
        self._drain_queue()
        self._apply_filter_sort()
        try:
            delay = int(float(self.interval_var.get()) * 1000)
        except Exception:
            delay = 3000
        self._after_id = self.after(delay, self._auto_refresh)

    def _on_close(self) -> None:
        if self._after_id is not None:
            self.after_cancel(self._after_id)
        self._watcher.stop()
        self._watcher.join(timeout=1.0)
        self.destroy()
