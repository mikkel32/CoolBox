"""Force Quit dialog for terminating processes."""

from __future__ import annotations

import os
import signal
import subprocess
import shutil
from pathlib import Path

import re
import time
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty, Full
from dataclasses import dataclass, field
from collections import deque
import heapq
import tkinter as tk
from tkinter import messagebox, filedialog
from tkinter import ttk

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
    samples: deque[float] = field(default_factory=deque)
    io_samples: deque[float] = field(default_factory=deque)
    max_samples: int = 5

    def __post_init__(self) -> None:
        self.samples = deque(self.samples, maxlen=self.max_samples)
        self.io_samples = deque(self.io_samples, maxlen=self.max_samples)

    def __lt__(self, other: "ProcessEntry") -> bool:
        """Order entries by average CPU then memory then PID."""
        if not isinstance(other, ProcessEntry):
            return NotImplemented
        return (
            self.avg_cpu,
            self.mem,
            self.pid,
        ) < (
            other.avg_cpu,
            other.mem,
            other.pid,
        )

    def add_sample(self, cpu: float, io: float) -> None:
        self.samples.append(cpu)
        self.io_samples.append(io)

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

    def changed_basic(self, other: "ProcessEntry") -> bool:
        """Return True if basic metrics changed since ``other``."""
        return any(
            [
                self.name != other.name,
                self.user != other.user,
                self.mem != other.mem,
                self.status != other.status,
                abs(self.cpu - other.cpu) > 0.1,
                self.threads != other.threads,
                abs(self.io_rate - other.io_rate) > 0.1,
            ]
        )


class ProcessWatcher(threading.Thread):
    """Background thread streaming process snapshots to the UI.

    Metrics are gathered concurrently using a thread pool. Expensive details
    like open file and connection counts are refreshed every ``detail_interval``
    cycles to keep overhead low. Updates are pushed through ``queue`` as
    ``(updates, removed)`` pairs where ``updates`` is a mapping of PID to
    ``ProcessEntry`` instances and ``removed`` is the set of PIDs that have
    disappeared since the last refresh. ``process_count`` tracks how many
    processes were seen in the most recent refresh cycle so the UI can display
    totals without recalculating them each time.
    """

    def __init__(
        self,
        queue: Queue[tuple[dict[int, ProcessEntry], set[int]]],
        interval: float = 2.0,
        detail_interval: int = 3,
        max_workers: int | None = None,
        sample_size: int = 5,
        limit: int | None = None,
        adaptive: bool = True,
        adaptive_detail: bool = True,
        *,
        conn_interval: float = 2.0,
        file_interval: float = 2.0,
        cache_ttl: float = 30.0,
        conn_global_threshold: int = 50,
        file_global_threshold: int = 50,
    ) -> None:
        super().__init__(daemon=True)
        self.queue = queue
        self.interval = max(0.5, float(interval))
        self.target_interval = self.interval
        self.detail_interval = max(1, detail_interval)
        self.target_detail_interval = self.detail_interval
        self.limit = limit
        self.adaptive = adaptive
        self.adaptive_detail = adaptive_detail
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._snapshot: dict[int, ProcessEntry] = {}
        self._detail_ts: dict[int, float] = {}
        self._conn_cache: dict[int, tuple[int, float]] = {}
        self._file_cache: dict[int, tuple[int, float]] = {}
        self._file_future = None
        self._global_conn_future = None
        self._global_file_future = None
        self._global_conn_data: dict[int, int] = {}
        self._global_conn_ts = 0.0
        self._global_file_data: dict[int, int] = {}
        self._global_file_ts = 0.0
        self.conn_interval = float(conn_interval)
        self.file_interval = float(file_interval)
        self.cache_ttl = float(cache_ttl)
        self.conn_global_threshold = int(conn_global_threshold)
        self.file_global_threshold = int(file_global_threshold)
        self._last_ts = time.monotonic()
        workers = max_workers or min(8, (os.cpu_count() or 1) * 2)
        self._executor = ThreadPoolExecutor(max_workers=workers)
        self._cpu_count = psutil.cpu_count(logical=True) or (os.cpu_count() or 1)
        self.sample_size = max(1, sample_size)
        self.process_count = 0
        self._last_detail_count = 0

    def set_interval(self, interval: float) -> None:
        self.target_interval = max(0.5, float(interval))
        self.interval = self.target_interval

    def set_detail_interval(self, interval: int) -> None:
        self.target_detail_interval = max(1, int(interval))
        self.detail_interval = self.target_detail_interval

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def run(self) -> None:
        while not self._stop_event.is_set():
            loop_start = time.monotonic()
            self._prune_caches(loop_start)
            if (
                self.process_count > self.conn_global_threshold * 2
                and self._global_conn_future is None
                and (
                    not self._global_conn_data
                    or loop_start - self._global_conn_ts > self.conn_interval
                )
            ):
                self._global_conn_future = self._executor.submit(
                    psutil.net_connections, kind="inet"
                )
            if (
                self.process_count > self.file_global_threshold * 2
                and os.path.isdir("/proc")
                and self._global_file_future is None
                and (
                    not self._global_file_data
                    or loop_start - self._global_file_ts > self.file_interval
                )
            ):
                self._global_file_future = self._executor.submit(
                    self._scan_fd_proc_all
                )
            if self._pause_event.is_set():
                if self._stop_event.wait(self.interval):
                    break
                continue

            now = time.monotonic()
            delta = max(now - self._last_ts, 0.001)
            self._last_ts = now
            updates: dict[int, ProcessEntry] = {}
            current: set[int] = set()

            basic_attrs = [
                "pid",
                "name",
                "username",
                "create_time",
                "memory_info",
                "status",
                "cpu_times",
                "num_threads",
                "io_counters",
            ]

            self.process_count = 0

            def collect(proc: psutil.Process) -> tuple[ProcessEntry, bool] | None:
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
                        io = proc.info.get("io_counters")
                        if io:
                            read_bytes = io.read_bytes
                            write_bytes = io.write_bytes
                        else:
                            read_bytes = write_bytes = 0
                except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                    return None

                prev = self._snapshot.get(pid)
                if prev is not None:
                    cpu = (cpu_time - prev.cpu_time) / delta / self._cpu_count * 100
                    io_rate = (
                        (read_bytes - prev.read_bytes + write_bytes - prev.write_bytes)
                        / delta
                        / (1024 * 1024)
                    )
                    changed = prev.changed_basic(
                        ProcessEntry(
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
                            files=prev.files,
                            conns=prev.conns,
                            io_rate=round(io_rate, 1),
                            samples=list(prev.samples),
                            io_samples=list(prev.io_samples),
                            max_samples=self.sample_size,
                        )
                    )
                    prev.cpu = round(cpu, 1)
                    prev.mem = round(mem, 1)
                    prev.user = user
                    prev.start = start
                    prev.status = status
                    prev.cpu_time = cpu_time
                    prev.threads = threads
                    prev.read_bytes = read_bytes
                    prev.write_bytes = write_bytes
                    prev.io_rate = round(io_rate, 1)
                    prev.add_sample(prev.cpu, prev.io_rate)
                    return prev, changed

                entry = ProcessEntry(
                    pid=pid,
                    name=name,
                    cpu=0.0,
                    mem=round(mem, 1),
                    user=user,
                    start=start,
                    status=status,
                    cpu_time=cpu_time,
                    threads=threads,
                    read_bytes=read_bytes,
                    write_bytes=write_bytes,
                    files=0,
                    conns=0,
                    io_rate=0.0,
                    samples=[],
                    io_samples=[],
                    max_samples=self.sample_size,
                )
                entry.add_sample(entry.cpu, entry.io_rate)
                return entry, True

            heap: list[tuple[tuple[float, float, int], ProcessEntry]] = []
            entries: list[ProcessEntry] = []
            detail_candidates: list[ProcessEntry] = []
            now_ts = time.monotonic()

            proc_iter = psutil.process_iter(basic_attrs)
            for result in self._executor.map(collect, proc_iter):
                self.process_count += 1
                if not result:
                    continue
                entry, changed_flag = result
                if self.limit:
                    score = (entry.avg_cpu, entry.mem, entry.pid)
                    item = (score, entry, changed_flag)
                    if len(heap) < self.limit:
                        heapq.heappush(heap, item)
                    else:
                        heapq.heappushpop(heap, item)
                else:
                    entries.append((entry, changed_flag))

            if self.limit:
                entries = [
                    (e, ch) for _s, e, ch in heapq.nlargest(self.limit, heap)
                ]

            for entry, changed in entries:
                current.add(entry.pid)
                if changed:
                    updates[entry.pid] = entry
                if changed or now_ts - self._detail_ts.get(entry.pid, 0.0) >= self.detail_interval:
                    detail_candidates.append(entry)
                self._snapshot[entry.pid] = entry
            if not self.limit:
                entries.sort(key=lambda ec: (ec[0].cpu, ec[0].mem), reverse=True)

            if detail_candidates:
                now_conn = time.monotonic()
                now_file = now_conn
                cand_pids = {e.pid for e in detail_candidates}
                fetch = [
                    p
                    for p in cand_pids
                    if now_conn - self._conn_cache.get(p, (0, 0))[1]
                    >= self.conn_interval
                ]
                file_fetch = [
                    p
                    for p in cand_pids
                    if now_file - self._file_cache.get(p, (0, 0))[1]
                    >= self.file_interval
                ]
                conn_counts: dict[int, int] = {}
                if fetch:
                    if len(fetch) > self.conn_global_threshold:
                        if self._global_conn_future and self._global_conn_future.done():
                            all_conns = self._global_conn_future.result()
                            self._global_conn_future = None
                            counts: dict[int, int] = {}
                            for conn in all_conns:
                                pid = conn.pid
                                if pid is None:
                                    continue
                                counts[pid] = counts.get(pid, 0) + 1
                            self._global_conn_data = counts
                            self._global_conn_ts = now_conn
                            for pid, cnt in counts.items():
                                self._conn_cache[pid] = (cnt, now_conn)
                            conn_counts = {pid: counts.get(pid, 0) for pid in cand_pids}
                        elif self._global_conn_data:
                            for pid in fetch:
                                if pid in self._global_conn_data:
                                    conn_counts[pid] = self._global_conn_data[pid]
                    else:
                        def _get_conn(pid: int) -> tuple[int, int] | None:
                            try:
                                return pid, len(psutil.Process(pid).connections(kind="inet"))
                            except Exception:
                                return None

                        for res in self._executor.map(_get_conn, fetch):
                            if not res:
                                continue
                            pid, cnt = res
                            conn_counts[pid] = cnt
                            self._conn_cache[pid] = (cnt, now_conn)
                for pid in cand_pids:
                    if pid not in conn_counts and pid in self._conn_cache:
                        conn_counts[pid] = self._conn_cache[pid][0]

                file_counts: dict[int, int] = {}

                def _get_file_count(pid: int) -> tuple[int, int] | None:
                    try:
                        proc_path = f"/proc/{pid}/fd"
                        if os.path.isdir(proc_path):
                            return pid, sum(1 for _ in os.scandir(proc_path))
                        proc = psutil.Process(pid)
                        with proc.oneshot():
                            if hasattr(proc, "num_handles"):
                                return pid, proc.num_handles()
                            if hasattr(proc, "num_fds"):
                                return pid, proc.num_fds()
                            return pid, len(proc.open_files())
                    except Exception:
                        return None

                if file_fetch:
                    if (
                        len(file_fetch) > self.file_global_threshold
                        and os.path.isdir("/proc")
                    ):
                        if self._global_file_future and self._global_file_future.done():
                            self._global_file_data = self._global_file_future.result()
                            self._global_file_ts = now_file
                            self._global_file_future = None
                        if self._global_file_data:
                            for pid in file_fetch:
                                if pid in self._global_file_data:
                                    file_counts[pid] = self._global_file_data[pid]
                        else:
                            if self._file_future is None:
                                self._file_future = self._executor.submit(
                                    self._scan_fd_proc, set(file_fetch)
                                )
                            if self._file_future and self._file_future.done():
                                all_counts = self._file_future.result()
                                self._file_future = None
                                file_counts.update(all_counts)
                    else:
                        for res in self._executor.map(_get_file_count, file_fetch):
                            if not res:
                                continue
                            pid, count = res
                            file_counts[pid] = count
                    for pid in file_fetch:
                        self._file_cache[pid] = (
                            file_counts.get(pid, self._file_cache.get(pid, (0, 0))[0]),
                            now_file,
                        )
                for pid in cand_pids:
                    if pid not in file_counts and pid in self._file_cache:
                        file_counts[pid] = self._file_cache[pid][0]

                def gather_detail(entry: ProcessEntry) -> ProcessEntry:
                    try:
                        entry.files = file_counts.get(entry.pid, entry.files)
                    except Exception:
                        pass
                    entry.conns = conn_counts.get(entry.pid, entry.conns)
                    return entry
                detail_start = time.monotonic()
                for det in self._executor.map(gather_detail, detail_candidates):
                    updates[det.pid] = det
                    self._snapshot[det.pid] = det
                    self._detail_ts[det.pid] = time.monotonic()
                detail_elapsed = time.monotonic() - detail_start
                if self.adaptive_detail:
                    if detail_elapsed > self.target_interval / 3:
                        self.detail_interval = min(
                            self.detail_interval + 1,
                            self.target_detail_interval * 5,
                        )
                    elif (
                        detail_elapsed < self.target_interval / 10
                        and self.detail_interval > self.target_detail_interval
                    ):
                        self.detail_interval = max(
                            self.detail_interval - 1,
                            self.target_detail_interval,
                        )
                self._last_detail_count = len(detail_candidates)

            else:
                self._last_detail_count = 0

            removed = set(self._snapshot) - current

            if updates or removed:
                try:
                    self.queue.put_nowait((updates, removed))
                except Full:
                    try:
                        self.queue.get_nowait()
                    except Empty:
                        pass
                    self.queue.put_nowait((updates, removed))
                for pid in removed:
                    self._snapshot.pop(pid, None)
                    self._detail_ts.pop(pid, None)
                    self._conn_cache.pop(pid, None)
                    self._file_cache.pop(pid, None)

            if self.adaptive:
                elapsed = time.monotonic() - loop_start
                if elapsed > self.target_interval * 1.5:
                    self.interval = min(self.interval * 1.25, self.target_interval * 5)
                elif elapsed < self.target_interval * 0.7 and self.interval > self.target_interval:
                    self.interval = max(self.interval * 0.9, self.target_interval)

            if self._stop_event.wait(self.interval):
                break

    def stop(self) -> None:
        self._stop_event.set()
        self._executor.shutdown(wait=False)

    def _prune_caches(self, now: float) -> None:
        """Drop stale connection and file count cache entries."""
        stale = [pid for pid, (_, ts) in self._conn_cache.items() if now - ts > self.cache_ttl]
        for pid in stale:
            self._conn_cache.pop(pid, None)
        stale = [pid for pid, (_, ts) in self._file_cache.items() if now - ts > self.cache_ttl]
        for pid in stale:
            self._file_cache.pop(pid, None)
        if now - self._global_conn_ts > self.cache_ttl:
            self._global_conn_data.clear()
        if now - self._global_file_ts > self.cache_ttl:
            self._global_file_data.clear()

    def _scan_fd_proc(self, pids: set[int]) -> dict[int, int]:
        """Return open file counts for *pids* by scanning /proc."""
        counts: dict[int, int] = {}
        proc_root = Path("/proc")
        for entry in os.scandir(proc_root):
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid not in pids:
                continue
            fd_path = os.path.join(entry.path, "fd")
            if os.path.isdir(fd_path):
                try:
                    counts[pid] = sum(1 for _ in os.scandir(fd_path))
                except Exception:
                    continue
            if len(counts) == len(pids):
                break
        return counts

    def _scan_fd_proc_all(self) -> dict[int, int]:
        """Return open file counts for all processes by scanning /proc."""
        counts: dict[int, int] = {}
        proc_root = Path("/proc")
        for entry in os.scandir(proc_root):
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            fd_path = os.path.join(entry.path, "fd")
            if os.path.isdir(fd_path):
                try:
                    counts[pid] = sum(1 for _ in os.scandir(fd_path))
                except Exception:
                    continue
        return counts


class ForceQuitDialog(ctk.CTkToplevel):
    """Dialog showing running processes that can be terminated."""

    def __init__(self, app):
        super().__init__(app.window)
        self.app = app
        self.title("Force Quit")
        width_env = os.getenv("FORCE_QUIT_WIDTH")
        height_env = os.getenv("FORCE_QUIT_HEIGHT")
        sort_env = os.getenv("FORCE_QUIT_SORT")
        reverse_env = os.getenv("FORCE_QUIT_SORT_REVERSE")
        on_top_env = os.getenv("FORCE_QUIT_ON_TOP")
        cfg = app.config
        width = (
            int(width_env)
            if width_env and width_env.isdigit()
            else int(cfg.get("force_quit_width", 1000))
        )
        height = (
            int(height_env)
            if height_env and height_env.isdigit()
            else int(cfg.get("force_quit_height", 650))
        )
        self.resizable(True, True)
        self.geometry(f"{width}x{height}")
        if on_top_env is not None:
            on_top = on_top_env.lower() in {"1", "true", "yes"}
        else:
            on_top = bool(cfg.get("force_quit_on_top", False))
        self.attributes("-topmost", on_top)
        self._after_id: int | None = None
        self._debounce_id: int | None = None
        self.process_snapshot: dict[int, ProcessEntry] = {}
        self._row_cache: dict[int, tuple[tuple, tuple]] = {}
        self._queue: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue(maxsize=1)
        self.paused = False
        if reverse_env is not None:
            self.sort_reverse = reverse_env.lower() in {"1", "true", "yes"}
        else:
            self.sort_reverse = bool(cfg.get("force_quit_sort_reverse", True))
        self.sort_default = sort_env or str(cfg.get("force_quit_sort", "CPU"))
        self._filter_cache: tuple[str, str, str, bool] | None = None
        self._snapshot_changed = False
        interval_env = os.getenv("FORCE_QUIT_INTERVAL")
        detail_env = os.getenv("FORCE_QUIT_DETAIL_INTERVAL")
        max_env = os.getenv("FORCE_QUIT_MAX")
        worker_env = os.getenv("FORCE_QUIT_WORKERS")
        cpu_alert_env = os.getenv("FORCE_QUIT_CPU_ALERT")
        mem_alert_env = os.getenv("FORCE_QUIT_MEM_ALERT")
        sample_env = os.getenv("FORCE_QUIT_SAMPLES")
        adaptive_env = os.getenv("FORCE_QUIT_ADAPTIVE")
        adaptive_detail_env = os.getenv("FORCE_QUIT_ADAPTIVE_DETAIL")
        conn_interval_env = os.getenv("FORCE_QUIT_CONN_INTERVAL")
        file_interval_env = os.getenv("FORCE_QUIT_FILE_INTERVAL")
        cache_ttl_env = os.getenv("FORCE_QUIT_CACHE_TTL")
        conn_global_env = os.getenv("FORCE_QUIT_CONN_GLOBAL")
        file_global_env = os.getenv("FORCE_QUIT_FILE_GLOBAL")
        auto_env = os.getenv("FORCE_QUIT_AUTO_KILL", "").lower()

        workers = int(worker_env) if worker_env and worker_env.isdigit() else None
        interval = (
            float(interval_env)
            if interval_env
            else float(cfg.get("force_quit_interval", 2.0))
        )
        detail = (
            int(detail_env)
            if detail_env and detail_env.isdigit()
            else int(cfg.get("force_quit_detail_interval", 5))
        )
        samples = (
            int(sample_env)
            if sample_env and sample_env.isdigit()
            else int(cfg.get("force_quit_samples", 5))
        )
        conn_interval = (
            float(conn_interval_env)
            if conn_interval_env
            else float(cfg.get("force_quit_conn_interval", 2.0))
        )
        file_interval = (
            float(file_interval_env)
            if file_interval_env
            else float(cfg.get("force_quit_file_interval", 2.0))
        )
        cache_ttl = (
            float(cache_ttl_env)
            if cache_ttl_env
            else float(cfg.get("force_quit_cache_ttl", 30.0))
        )
        conn_global = (
            int(conn_global_env)
            if conn_global_env and conn_global_env.isdigit()
            else int(cfg.get("force_quit_conn_global", 50))
        )
        file_global = (
            int(file_global_env)
            if file_global_env and file_global_env.isdigit()
            else int(cfg.get("force_quit_file_global", 50))
        )
        self.cpu_alert = (
            float(cpu_alert_env)
            if cpu_alert_env
            else float(cfg.get("force_quit_cpu_alert", 80.0))
        )
        self.mem_alert = (
            float(mem_alert_env)
            if mem_alert_env
            else float(cfg.get("force_quit_mem_alert", 500.0))
        )
        self.adaptive_refresh = (
            adaptive_env.lower() in {"1", "true", "yes"}
            if adaptive_env is not None
            else bool(cfg.get("force_quit_adaptive", True))
        )
        self.adaptive_detail = (
            adaptive_detail_env.lower() in {"1", "true", "yes"}
            if adaptive_detail_env is not None
            else bool(cfg.get("force_quit_adaptive_detail", True))
        )
        self.max_processes = (
            int(max_env)
            if max_env and max_env.isdigit()
            else int(cfg.get("force_quit_max", 300))
        )
        auto_setting = cfg.get("force_quit_auto_kill", "none").lower()
        self.auto_kill_cpu = (
            "cpu" in auto_env
            or "both" in auto_env
            or auto_setting in ("cpu", "both")
        )
        self.auto_kill_mem = (
            "mem" in auto_env
            or "both" in auto_env
            or auto_setting in ("mem", "both")
        )
        self._watcher = ProcessWatcher(
            self._queue,
            interval=interval,
            detail_interval=detail,
            max_workers=workers,
            sample_size=samples,
            limit=self.max_processes,
            adaptive=self.adaptive_refresh,
            adaptive_detail=self.adaptive_detail,
            conn_interval=conn_interval,
            file_interval=file_interval,
            cache_ttl=cache_ttl,
            conn_global_threshold=conn_global,
            file_global_threshold=file_global,
        )
        self._watcher.start()
        self.after(0, self._auto_refresh)

        ctk.CTkLabel(
            self,
            text="Force Quit Running Processes",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(pady=10)

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True)
        monitor_tab = self.tabview.add("Monitor")
        actions_tab = self.tabview.add("Actions")

        actions_scroll = ctk.CTkScrollableFrame(actions_tab)
        actions_scroll.pack(fill="both", expand=True, padx=10, pady=10)
        actions = [
            ("Kill by Name", self._kill_by_name),
            ("Kill by Pattern", self._kill_by_pattern),
            ("Kill by Port", self._kill_by_port),
            ("Kill by Host", self._kill_by_host),
            ("Kill by File", self._kill_by_file),
            ("Kill by Exec", self._kill_by_executable),
            ("Kill by User", self._kill_by_user),
            ("Kill by Cmdline", self._kill_by_cmdline),
            ("Kill High CPU", self._kill_high_cpu),
            ("Kill High Mem", self._kill_high_memory),
            ("Kill High IO", self._kill_high_io),
            ("Kill CPU Avg", self._kill_high_cpu_avg),
            ("Kill Many Threads", self._kill_high_threads),
            ("Kill Many Files", self._kill_high_files),
            ("Kill Many Conns", self._kill_high_conns),
            ("Kill by Parent", self._kill_by_parent),
            ("Kill Children", self._kill_children),
            ("Kill by Age", self._kill_by_age),
            ("Kill Zombies", self._kill_zombies),
        ]
        for i, (text, cmd) in enumerate(actions):
            btn = ctk.CTkButton(actions_scroll, text=text, command=cmd)
            btn.grid(row=i // 2, column=i % 2, padx=5, pady=5, sticky="ew")
        actions_scroll.grid_columnconfigure(0, weight=1)
        actions_scroll.grid_columnconfigure(1, weight=1)

        search_frame = ctk.CTkFrame(monitor_tab, fg_color="transparent")
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

        self.sort_var = ctk.StringVar(value=self.sort_default)
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

        self.interval_var = ctk.StringVar(value=str(interval))
        interval_menu = ctk.CTkOptionMenu(
            search_frame,
            variable=self.interval_var,
            values=["1", "2", "5"],
            command=lambda v: self._watcher.set_interval(float(v)),
        )
        interval_menu.pack(side="left", padx=5)

        self.detail_var = ctk.StringVar(value=str(detail))
        detail_menu = ctk.CTkOptionMenu(
            search_frame,
            variable=self.detail_var,
            values=["2", "3", "5", "10"],
            command=lambda v: self._watcher.set_detail_interval(int(v)),
        )
        detail_menu.pack(side="left", padx=5)

        self.max_var = ctk.StringVar(value=str(self.max_processes))
        max_menu = ctk.CTkOptionMenu(
            search_frame,
            variable=self.max_var,
            values=["100", "200", "300", "500", "1000"],
            command=lambda v: self._set_max_processes(int(v)),
        )
        max_menu.pack(side="left", padx=5)
        self.pause_btn = ctk.CTkButton(
            search_frame, text="Pause", command=self._toggle_pause
        )
        self.pause_btn.pack(side="left", padx=5)
        ctk.CTkButton(search_frame, text="Refresh", command=self._populate).pack(
            side="left", padx=5
        )
        ctk.CTkButton(search_frame, text="Save CSV", command=self._export_csv).pack(
            side="left", padx=5
        )
        # Advanced actions live on the Actions tab

        options_frame = ctk.CTkFrame(monitor_tab, fg_color="transparent")
        options_frame.pack(fill="x", padx=10, pady=(5, 0))
        self.cpu_alert_var = ctk.StringVar(value=str(self.cpu_alert))
        self.mem_alert_var = ctk.StringVar(value=str(self.mem_alert))
        self.auto_cpu_var = ctk.BooleanVar(value=self.auto_kill_cpu)
        self.auto_mem_var = ctk.BooleanVar(value=self.auto_kill_mem)
        ctk.CTkLabel(options_frame, text="CPU ≥").pack(side="left")
        ctk.CTkEntry(options_frame, width=60, textvariable=self.cpu_alert_var).pack(side="left", padx=5)
        ctk.CTkCheckBox(
            options_frame,
            text="Auto Kill CPU",
            variable=self.auto_cpu_var,
            command=lambda: setattr(self, "auto_kill_cpu", self.auto_cpu_var.get()),
        ).pack(side="left", padx=5)
        ctk.CTkLabel(options_frame, text="Mem ≥ MB").pack(side="left", padx=(10, 0))
        ctk.CTkEntry(options_frame, width=60, textvariable=self.mem_alert_var).pack(side="left", padx=5)
        ctk.CTkCheckBox(
            options_frame,
            text="Auto Kill Mem",
            variable=self.auto_mem_var,
            command=lambda: setattr(self, "auto_kill_mem", self.auto_mem_var.get()),
        ).pack(side="left", padx=5)
        ctk.CTkButton(options_frame, text="Apply", command=self._apply_thresholds).pack(side="left", padx=5)
        self.show_details_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options_frame,
            text="Show Details",
            variable=self.show_details_var,
            command=self._toggle_details,
        ).pack(side="left", padx=5)
        self.adaptive_var = ctk.BooleanVar(value=self.adaptive_refresh)
        ctk.CTkCheckBox(
            options_frame,
            text="Adaptive",
            variable=self.adaptive_var,
            command=lambda: self._toggle_adaptive(self.adaptive_var.get()),
        ).pack(side="left", padx=5)
        self.adaptive_detail_var = ctk.BooleanVar(value=self.adaptive_detail)
        ctk.CTkCheckBox(
            options_frame,
            text="Adaptive Detail",
            variable=self.adaptive_detail_var,
            command=lambda: self._toggle_adaptive_detail(self.adaptive_detail_var.get()),
        ).pack(side="left", padx=5)

        self.tree_frame = ctk.CTkFrame(monitor_tab)
        self.tree_frame.pack(fill="both", expand=True, padx=10, pady=10)
        columns = [
            "PID",
            "User",
            "Name",
            "CPU",
            "Avg CPU",
            "Mem",
            "IO",
            "Avg IO",
            "Threads",
            "Files",
            "Conns",
            "Status",
            "Age",
        ]
        self.tree = ttk.Treeview(
            self.tree_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
        )
        vsb = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self.tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree_frame.grid_rowconfigure(0, weight=1)
        self.tree_frame.grid_columnconfigure(0, weight=1)
        for col in columns:
            self.tree.heading(col, text=col, command=lambda c=col: self._sort_by_column(c))
            width = 60 if col in {"PID", "CPU", "Mem", "Avg CPU", "Avg IO"} else 90
            self.tree.column(col, width=width, anchor="w")
        default_col = self.sort_var.get()
        self.tree.heading(default_col, text=default_col + " \u25BC")
        self.tree.tag_configure("high_cpu", background="#ffdddd")
        self.tree.tag_configure("high_mem", background="#fff5cc")
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_selection)

        self.details_frame = ctk.CTkFrame(monitor_tab)
        self.details_frame.pack(fill="both", padx=10, pady=(5, 0))
        self.details_text = ctk.CTkTextbox(self.details_frame, height=120)
        self.details_text.pack(fill="both", expand=True)
        self.details_text.configure(state="disabled")
        self._toggle_details()

        ctk.CTkButton(
            monitor_tab, text="Force Quit Selected", command=self._kill_selected
        ).pack(pady=(5, 0))

        self.status_var = ctk.StringVar(value="0 processes")
        ctk.CTkLabel(monitor_tab, textvariable=self.status_var).pack(pady=(0, 5))

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._auto_refresh()

    def _drain_queue(self) -> None:
        changed = False
        while not self._queue.empty():
            updates, removed = self._queue.get_nowait()
            if updates or removed:
                changed = True
            self.process_snapshot.update(updates)
            for pid in removed:
                self.process_snapshot.pop(pid, None)
        if changed:
            self._snapshot_changed = True

    @staticmethod
    def _find_over_threshold(
        snapshot: dict[int, ProcessEntry],
        *,
        kill_cpu: bool,
        kill_mem: bool,
        cpu_alert: float,
        mem_alert: float,
    ) -> list[int]:
        """Return PIDs exceeding the configured CPU or memory thresholds."""

        pids: list[int] = []
        for entry in snapshot.values():
            if kill_cpu and entry.avg_cpu >= cpu_alert:
                pids.append(entry.pid)
                continue
            if kill_mem and entry.mem >= mem_alert:
                pids.append(entry.pid)
        return pids

    @staticmethod
    def force_kill(pid: int, *, timeout: float = 3.0) -> bool:
        """Forcefully terminate ``pid`` and return ``True`` if it exited."""
        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return False

        try:
            proc.terminate()
            proc.wait(timeout=timeout / 2)
            return True
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            pass
        except (psutil.AccessDenied, PermissionError):
            pass

        try:
            proc.kill()
            proc.wait(timeout=timeout / 2)
            return True
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            pass
        except (psutil.AccessDenied, PermissionError):
            pass

        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], check=False)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                return False
        try:
            psutil.Process(pid).wait(timeout=timeout)
            return True
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            pass

        try:
            status = psutil.Process(pid).status()
            return status in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}
        except psutil.NoSuchProcess:
            return True
        except Exception:
            return False

    @classmethod
    def force_kill_multiple(cls, pids: list[int]) -> int:
        """Kill multiple PIDs concurrently and return number successfully killed."""

        def kill_one(pid: int) -> bool:
            try:
                return cls.force_kill(pid)
            except Exception:
                return False

        if not pids:
            return 0
        if len(pids) == 1:
            return int(kill_one(pids[0]))

        with ThreadPoolExecutor(max_workers=min(len(pids), 8)) as ex:
            results = ex.map(kill_one, pids)
        return sum(1 for ok in results if ok)

    @classmethod
    def force_kill_by_name(cls, name: str) -> int:
        """Kill all processes with the given name. Returns number killed."""
        pids: list[int] = [
            proc.pid
            for proc in psutil.process_iter(["pid", "name"])
            if proc.info.get("name", "").lower() == name.lower()
        ]
        return cls.force_kill_multiple(pids)

    @classmethod
    def force_kill_by_pattern(cls, regex: re.Pattern[str]) -> int:
        """Kill processes whose names match regex. Returns number killed."""
        pids: list[int] = [
            proc.pid
            for proc in psutil.process_iter(["pid", "name"])
            if regex.search(proc.info.get("name", ""))
        ]
        return cls.force_kill_multiple(pids)

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
        target = os.path.abspath(path)
        lsof = shutil.which("lsof")
        pids: set[int] = set()
        if lsof:
            result = subprocess.run(
                [lsof, "-t", target], capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                try:
                    pids.add(int(line.strip()))
                except ValueError:
                    continue
        if not pids:
            for proc in psutil.process_iter(["pid"]):
                try:
                    files = proc.open_files()
                    if any(os.path.abspath(f.path) == target for f in files):
                        pids.add(proc.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        return cls.force_kill_multiple(list(pids))

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
        if alive:
            ForceQuitDialog.force_kill_multiple([p.pid for p in alive])
            psutil.wait_procs(alive, timeout=timeout)

    @classmethod
    def force_kill_by_executable(
        cls, regex: re.Pattern[str], *, exclude_self: bool = True
    ) -> int:
        """Kill processes whose executable path matches regex."""
        self_pid = os.getpid() if exclude_self else None
        pids: list[int] = []
        for proc in psutil.process_iter(["pid", "exe"]):
            if exclude_self and proc.pid == self_pid:
                continue
            exe = proc.info.get("exe") or ""
            if exe and regex.search(exe):
                pids.append(proc.pid)
        return cls.force_kill_multiple(pids)

    @classmethod
    def force_kill_by_user(
        cls,
        username: str,
        *,
        exe_regex: re.Pattern[str] | None = None,
        exclude_self: bool = True,
    ) -> int:
        """Kill processes for a user optionally filtered by executable regex."""
        self_pid = os.getpid() if exclude_self else None
        pids: list[int] = []
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
            pids.append(proc.pid)
        return cls.force_kill_multiple(pids)

    @classmethod
    def force_kill_by_cmdline(cls, regex: re.Pattern[str]) -> int:
        """Kill processes whose command line matches regex."""
        pids: list[int] = []
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmd = " ".join(proc.info.get("cmdline") or [])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if regex.search(cmd):
                pids.append(proc.pid)
        return cls.force_kill_multiple(pids)

    @classmethod
    def force_kill_above_cpu(cls, threshold: float) -> int:
        """Kill processes using more CPU percent than threshold."""
        pids: list[int] = []
        for proc in psutil.process_iter(["pid"]):
            try:
                if proc.cpu_percent(interval=0.1) > threshold:
                    pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return cls.force_kill_multiple(pids)

    @classmethod
    def force_kill_above_memory(cls, threshold_mb: float) -> int:
        """Kill processes using more memory (MB) than threshold."""
        pids: list[int] = []
        for proc in psutil.process_iter(["pid", "memory_info"]):
            try:
                mem_mb = proc.info["memory_info"].rss / (1024 * 1024)
                if mem_mb > threshold_mb:
                    pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
        return cls.force_kill_multiple(pids)

    @classmethod
    def force_kill_above_threads(cls, threshold: int) -> int:
        """Kill processes with thread count greater than threshold."""
        pids: list[int] = []
        for proc in psutil.process_iter(["pid", "num_threads"]):
            try:
                if proc.info.get("num_threads", 0) > threshold:
                    pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
        return cls.force_kill_multiple(pids)

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
        pids: list[int] = []
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
                    pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue
        return cls.force_kill_multiple(pids)

    @classmethod
    def force_kill_above_files(cls, threshold: int) -> int:
        """Kill processes with more open files than ``threshold``."""
        pids: list[int] = []
        for proc in psutil.process_iter(["pid"]):
            try:
                if len(proc.open_files()) > threshold:
                    pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        return cls.force_kill_multiple(pids)

    @classmethod
    def force_kill_above_conns(cls, threshold: int) -> int:
        """Kill processes with more network connections than ``threshold``."""
        pids: list[int] = []
        for proc in psutil.process_iter(["pid"]):
            try:
                if len(proc.net_connections(kind="inet")) > threshold:
                    pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return cls.force_kill_multiple(pids)

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
        pids: list[int] = []
        for proc in psutil.process_iter(["pid", "cpu_times"]):
            try:
                start = snapshot.get(proc.pid)
                if start is None:
                    continue
                cpu = (sum(proc.cpu_times()) - start) / duration / psutil.cpu_count() * 100
                if cpu > threshold:
                    pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return cls.force_kill_multiple(pids)

    @classmethod
    def force_kill_by_parent(
        cls, parent_pid: int, *, include_parent: bool = False
    ) -> int:
        """Kill processes by parent PID."""
        try:
            parent = psutil.Process(parent_pid)
        except psutil.NoSuchProcess:
            return 0
        procs = parent.children(recursive=True)
        if include_parent:
            procs.append(parent)
        pids = [p.pid for p in procs]
        return cls.force_kill_multiple(pids)

    @classmethod
    def force_kill_children(cls, parent_pid: int) -> int:
        """Kill only the children of a process."""
        return cls.force_kill_by_parent(parent_pid, include_parent=False)

    @classmethod
    def force_kill_older_than(
        cls, seconds: float, cmd_regex: re.Pattern[str] | None = None
    ) -> int:
        """Kill processes older than ``seconds`` optionally filtered by command line."""
        now = time.time()
        pids: list[int] = []
        for proc in psutil.process_iter(["pid", "create_time", "cmdline"]):
            try:
                if proc.pid == os.getpid() or now - proc.info["create_time"] <= seconds:
                    continue
                if cmd_regex is not None:
                    cmd = " ".join(proc.info.get("cmdline") or [])
                    if not cmd_regex.search(cmd):
                        continue
                pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
        return cls.force_kill_multiple(pids)

    @classmethod
    def force_kill_zombies(cls) -> int:
        """Terminate processes in a zombie state."""
        pids: list[int] = []
        for proc in psutil.process_iter(["pid", "status"]):
            try:
                if proc.info.get("status") == psutil.STATUS_ZOMBIE:
                    pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
        return cls.force_kill_multiple(pids)

    def _populate(self) -> None:
        if self._debounce_id is not None:
            self.after_cancel(self._debounce_id)
        self._debounce_id = self.after(150, self._apply_filter_sort)

    def _current_filter_key(self) -> tuple[str, str, str, bool]:
        return (
            self.search_var.get().lower(),
            self.filter_var.get(),
            self.sort_var.get(),
            self.sort_reverse,
        )

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
        processes.sort(key=key_func, reverse=self.sort_reverse)
        if self.max_processes:
            processes = processes[: self.max_processes]
        self._update_list(processes)
        self._filter_cache = self._current_filter_key()

    def _update_list(self, processes: list[ProcessEntry]) -> None:
        def update_tree() -> None:
            existing = set(self.tree.get_children())
            for entry in processes:
                pid = str(entry.pid)
                age = round(time.time() - entry.start, 1)
                values = (
                    entry.pid,
                    (entry.user or "")[:8],
                    entry.name,
                    f"{entry.cpu:.1f}",
                    f"{entry.avg_cpu:.1f}",
                    f"{entry.mem:.1f}",
                    f"{entry.io_rate:.1f}",
                    f"{entry.avg_io:.1f}",
                    entry.threads,
                    entry.files,
                    entry.conns,
                    entry.status[:6],
                    age,
                )
                tags: list[str] = []
                if entry.cpu >= self.cpu_alert or entry.avg_cpu >= self.cpu_alert:
                    tags.append("high_cpu")
                if entry.mem >= self.mem_alert:
                    tags.append("high_mem")
                prev = self._row_cache.get(entry.pid)
                current = (values, tuple(tags))
                if prev != current:
                    if self.tree.exists(pid):
                        self.tree.item(pid, values=values, tags=tags)
                    else:
                        self.tree.insert("", "end", iid=pid, values=values, tags=tags)
                    self._row_cache[entry.pid] = current
                else:
                    if not self.tree.exists(pid):
                        self.tree.insert("", "end", iid=pid, values=values, tags=tags)
                existing.discard(pid)
            for iid in existing:
                self.tree.delete(iid)
                try:
                    self._row_cache.pop(int(iid), None)
                except ValueError:
                    pass

        self.after_idle(update_tree)
        self._update_status(len(processes))

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
        pids = [int(pid) for pid in self.tree.selection()]
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

    def _on_double_click(self, event) -> None:
        item = self.tree.identify_row(event.y)
        if item:
            self._confirm_kill(int(item))

    def _on_right_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Terminate", command=lambda pid=int(iid): self._confirm_kill(pid))
        menu.post(event.x_root, event.y_root)

    def _sort_by_column(self, col: str) -> None:
        current = self.sort_var.get()
        if col == current:
            self.sort_reverse = not self.sort_reverse
        else:
            self.tree.heading(current, text=current)
            self.sort_var.set(col)
            self.sort_reverse = True
        arrow = " \u25BC" if self.sort_reverse else " \u25B2"
        self.tree.heading(col, text=col + arrow)
        self._populate()

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        self.pause_btn.configure(text="Resume" if self.paused else "Pause")
        if self.paused:
            self._watcher.pause()
        else:
            self._watcher.resume()
            self._auto_refresh()

    def _toggle_adaptive(self, enabled: bool) -> None:
        """Enable or disable adaptive refresh."""
        self.adaptive_refresh = enabled
        self._watcher.adaptive = enabled

    def _toggle_adaptive_detail(self, enabled: bool) -> None:
        """Enable or disable adaptive detail refresh."""
        self.adaptive_detail = enabled
        self._watcher.adaptive_detail = enabled

    def _update_status(self, count: int) -> None:
        selected = len(self.tree.selection())
        total_cpu = sum(p.cpu for p in self.process_snapshot.values())
        total_mem = sum(p.mem for p in self.process_snapshot.values())
        total = self._watcher.process_count
        self.status_var.set(
            f"{count}/{total} processes ({selected} selected) | CPU {total_cpu:.1f}% | Mem {total_mem:.1f} MB"
        )

    def _on_selection(self, _event=None) -> None:
        self._update_status(len(self.tree.get_children()))
        self._show_details()

    def _show_details(self) -> None:
        sel = self.tree.selection()
        if not sel:
            self.details_text.configure(state="normal")
            self.details_text.delete("1.0", "end")
            self.details_text.configure(state="disabled")
            return
        pid = int(sel[0])
        info = self._get_process_details(pid)
        self.details_text.configure(state="normal")
        self.details_text.delete("1.0", "end")
        self.details_text.insert("1.0", info)
        self.details_text.configure(state="disabled")

    def _toggle_details(self) -> None:
        if self.show_details_var.get():
            self.details_frame.pack(fill="both", padx=10, pady=(5, 0))
            self._show_details()
        else:
            self.details_frame.pack_forget()

    def _get_process_details(self, pid: int) -> str:
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                name = proc.name()
                exe = proc.exe() or ""
                cmdline = " ".join(proc.cmdline())
                cwd = proc.cwd() or ""
                user = proc.username() or ""
                start = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(proc.create_time()))
                status = proc.status()
                mem = proc.memory_info().rss / (1024 * 1024)
                cpu = proc.cpu_percent(interval=0.1)
                threads = proc.num_threads()
                files = len(proc.open_files())
                conns = len(proc.connections(kind="inet"))
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            return str(exc)
        return (
            f"PID: {pid}\n"
            f"Name: {name}\n"
            f"User: {user}\n"
            f"Status: {status}\n"
            f"Started: {start}\n"
            f"CPU: {cpu:.1f}%\n"
            f"Memory: {mem:.1f} MB\n"
            f"Threads: {threads}\n"
            f"Open Files: {files}\n"
            f"Connections: {conns}\n"
            f"CWD: {cwd}\n"
            f"Executable: {exe}\n"
            f"Cmdline: {cmdline}"
        )

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

    def _set_max_processes(self, value: int) -> None:
        """Update the maximum number of processes to monitor."""
        self.max_processes = value
        self._watcher.limit = value
        cfg = self.app.config
        cfg.set("force_quit_max", value)
        cfg.save()
        self._populate()

    def _apply_thresholds(self) -> None:
        """Update alert thresholds and auto-kill flags from the UI."""
        try:
            self.cpu_alert = float(self.cpu_alert_var.get())
        except ValueError:
            pass
        try:
            self.mem_alert = float(self.mem_alert_var.get())
        except ValueError:
            pass
        self.auto_kill_cpu = self.auto_cpu_var.get()
        self.auto_kill_mem = self.auto_mem_var.get()
        self.adaptive_refresh = self.adaptive_var.get()
        self._watcher.adaptive = self.adaptive_refresh
        self.adaptive_detail = self.adaptive_detail_var.get()
        self._watcher.adaptive_detail = self.adaptive_detail
        cfg = self.app.config
        cfg.set("force_quit_cpu_alert", self.cpu_alert)
        cfg.set("force_quit_mem_alert", self.mem_alert)
        if self.auto_kill_cpu and self.auto_kill_mem:
            auto = "both"
        elif self.auto_kill_cpu:
            auto = "cpu"
        elif self.auto_kill_mem:
            auto = "mem"
        else:
            auto = "none"
        cfg.set("force_quit_auto_kill", auto)
        cfg.set("force_quit_adaptive", self.adaptive_refresh)
        cfg.set("force_quit_adaptive_detail", self.adaptive_detail)
        cfg.save()
        self._populate()

    def _auto_refresh(self) -> None:
        if not self.winfo_exists():
            return
        if self.paused:
            self._after_id = self.after(1000, self._auto_refresh)
            return
        self._drain_queue()
        key = self._current_filter_key()
        if self._snapshot_changed or key != self._filter_cache:
            self._apply_filter_sort()
            self._filter_cache = key
        if self.auto_kill_cpu or self.auto_kill_mem:
            pids = self._find_over_threshold(
                self.process_snapshot,
                kill_cpu=self.auto_kill_cpu,
                kill_mem=self.auto_kill_mem,
                cpu_alert=self.cpu_alert,
                mem_alert=self.mem_alert,
            )
            if pids:
                self.force_kill_multiple(pids)
                self._snapshot_changed = True
        self._snapshot_changed = False
        try:
            delay = int(float(self.interval_var.get()) * 1000)
        except Exception:
            delay = int(self._watcher.interval * 1000)
        self._after_id = self.after(delay, self._auto_refresh)

    def _on_close(self) -> None:
        self._apply_thresholds()
        cfg = self.app.config
        cfg.set("force_quit_width", self.winfo_width())
        cfg.set("force_quit_height", self.winfo_height())
        cfg.set("force_quit_sort", self.sort_var.get())
        cfg.set("force_quit_sort_reverse", self.sort_reverse)
        try:
            cfg.set("force_quit_interval", float(self.interval_var.get()))
        except Exception:
            pass
        try:
            cfg.set("force_quit_detail_interval", int(self.detail_var.get()))
        except Exception:
            pass
        try:
            cfg.set("force_quit_max", int(self.max_var.get()))
        except Exception:
            pass
        cfg.set("force_quit_adaptive", self.adaptive_refresh)
        cfg.set("force_quit_adaptive_detail", self.adaptive_detail)
        cfg.set("force_quit_on_top", bool(self.attributes("-topmost")))
        cfg.save()
        if self._after_id is not None:
            self.after_cancel(self._after_id)
        self._watcher.stop()
        self._watcher.join(timeout=1.0)
        self._row_cache.clear()
        self.destroy()
