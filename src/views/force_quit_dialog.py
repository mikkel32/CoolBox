"""Force Quit dialog for terminating processes."""

from __future__ import annotations

import os
import subprocess
import shutil
import tempfile
import logging
from pathlib import Path
from src.utils.window_utils import (
    WindowInfo,
    get_active_window,
    get_window_under_cursor,
    has_active_window_support,
    has_cursor_window_support,
    prime_window_cache,
)
from src.utils.kill_utils import kill_process, kill_process_tree
from src.utils import get_screen_refresh_rate

import re
import time
import socket
import sys
import threading
import traceback
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from typing import Any, Optional
import tkinter as tk
from tkinter import messagebox, filedialog
from tkinter import ttk

import json
from unittest.mock import Mock

import customtkinter as ctk
try:
    import psutil
except ImportError:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_psutil

    psutil = ensure_psutil()
from src.utils.process_monitor import ProcessEntry, ProcessWatcher
from .base_dialog import BaseDialog
from src.utils.color_utils import (
    hex_brightness,
    lighten_color,
    darken_color,
)
from src.utils.mouse_listener import get_global_listener

# Import the click overlay early so its heavy dependencies are loaded
# before the first "Kill by Click" invocation.
from .click_overlay import ClickOverlay, KILL_BY_CLICK_INTERVAL

KILL_BY_CLICK_WATCHDOG = 5.0
KILL_BY_CLICK_WATCHDOG_MISSES = 2

logger = logging.getLogger(__name__)


class ForceQuitDialog(BaseDialog):
    """Dialog showing running processes that can be terminated."""

    def __init__(self, app):
        super().__init__(app, title="Force Quit", resizable=(True, True))
        # Start the global mouse listener immediately so hooks are ready
        # before any click-to-kill actions.
        self._listener = get_global_listener()
        self._listener.start()
        # Instantiate the overlay in advance so showing it later is instant.
        prime_window_cache()
        cfg = app.config
        interval = cfg.get("kill_by_click_interval")
        min_interval = cfg.get("kill_by_click_min_interval")
        max_interval = cfg.get("kill_by_click_max_interval")
        if interval is None:
            interval = cfg.get("kill_by_click_interval_calibrated")
        if min_interval is None:
            min_interval = cfg.get("kill_by_click_min_interval_calibrated")
        if max_interval is None:
            max_interval = cfg.get("kill_by_click_max_interval_calibrated")
        if cfg.get("kill_by_click_auto_interval", True) and (
            interval is None or min_interval is None or max_interval is None
        ):
            interval, min_interval, max_interval = ClickOverlay.auto_tune_interval()
            try:
                cfg.set("kill_by_click_interval_calibrated", interval)
                cfg.set("kill_by_click_min_interval_calibrated", min_interval)
                cfg.set("kill_by_click_max_interval_calibrated", max_interval)
                cfg.save()
            except Exception:
                try:
                    cfg["kill_by_click_interval_calibrated"] = interval
                    cfg["kill_by_click_min_interval_calibrated"] = min_interval
                    cfg["kill_by_click_max_interval_calibrated"] = max_interval
                except Exception:
                    pass
        self._overlay = ClickOverlay(
            self,
            basic_render=cfg.get("basic_rendering", False),
            interval=interval if interval is not None else KILL_BY_CLICK_INTERVAL,
            min_interval=min_interval,
            max_interval=max_interval,
        )
        self._overlay.reset()
        self._configure_overlay()
        try:
            self._overlay._refresh_window_cache(
                int(getattr(self._overlay, "_cursor_x", 0)),
                int(getattr(self._overlay, "_cursor_y", 0)),
            )
        except Exception:
            pass

        width_env = os.getenv("FORCE_QUIT_WIDTH")
        height_env = os.getenv("FORCE_QUIT_HEIGHT")
        sort_env = os.getenv("FORCE_QUIT_SORT")
        reverse_env = os.getenv("FORCE_QUIT_SORT_REVERSE")
        on_top_env = os.getenv("FORCE_QUIT_ON_TOP")
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
        self._changed_tags: dict[int, int] = {}
        self._queue: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue(maxsize=1)
        self._enum_progress = 0.0
        self._actions_enabled = False
        self._overlay_thread: threading.Thread | None = None
        self._overlay_done: threading.Event | None = None
        self._overlay_watchdog_proc: subprocess.Popen[str] | None = None
        self._overlay_last_ping_file: str | None = None
        self._overlay_sync: threading.Thread | None = None
        self._overlay_poller: threading.Thread | None = None
        self._overlay_ctx: ForceQuitDialog._OverlayContext | None = None
        # Track whether the overlay has already been closed to avoid double
        # invocation when canceling Kill by Click operations.
        self._overlay_closed = False
        self.paused = False
        fps_env = os.getenv("FORCE_QUIT_FPS")
        if fps_env and fps_env.isdigit():
            self.target_fps = int(fps_env)
        else:
            self.target_fps = get_screen_refresh_rate()
        self.frame_delay = max(1, int(1000 / max(1, self.target_fps)))
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
        min_workers_env = os.getenv("FORCE_QUIT_MIN_WORKERS")
        max_workers_env = os.getenv("FORCE_QUIT_MAX_WORKERS")
        cpu_alert_env = os.getenv("FORCE_QUIT_CPU_ALERT")
        mem_alert_env = os.getenv("FORCE_QUIT_MEM_ALERT")
        sample_env = os.getenv("FORCE_QUIT_SAMPLES")
        visible_cpu_env = os.getenv("FORCE_QUIT_VISIBLE_CPU")
        visible_mem_env = os.getenv("FORCE_QUIT_VISIBLE_MEM")
        visible_io_env = os.getenv("FORCE_QUIT_VISIBLE_IO")
        visible_auto_env = os.getenv("FORCE_QUIT_VISIBLE_AUTO")
        hide_system_env = os.getenv("FORCE_QUIT_HIDE_SYSTEM")
        show_deltas_env = os.getenv("FORCE_QUIT_SHOW_DELTAS")
        adaptive_env = os.getenv("FORCE_QUIT_ADAPTIVE")
        auto_interval_env = os.getenv("FORCE_QUIT_AUTO_INTERVAL")
        adaptive_detail_env = os.getenv("FORCE_QUIT_ADAPTIVE_DETAIL")
        conn_interval_env = os.getenv("FORCE_QUIT_CONN_INTERVAL")
        file_interval_env = os.getenv("FORCE_QUIT_FILE_INTERVAL")
        cache_ttl_env = os.getenv("FORCE_QUIT_CACHE_TTL")
        conn_global_env = os.getenv("FORCE_QUIT_CONN_GLOBAL")
        file_global_env = os.getenv("FORCE_QUIT_FILE_GLOBAL")
        stable_cycles_env = os.getenv("FORCE_QUIT_STABLE_CYCLES")
        stable_skip_env = os.getenv("FORCE_QUIT_STABLE_SKIP")
        exclude_users_env = os.getenv("FORCE_QUIT_EXCLUDE_USERS")
        change_window_env = os.getenv("FORCE_QUIT_CHANGE_WINDOW")
        change_agg_env = os.getenv("FORCE_QUIT_CHANGE_AGG")
        change_score_env = os.getenv("FORCE_QUIT_CHANGE_SCORE")
        change_cpu_env = os.getenv("FORCE_QUIT_CHANGE_CPU")
        change_mem_env = os.getenv("FORCE_QUIT_CHANGE_MEM")
        change_io_env = os.getenv("FORCE_QUIT_CHANGE_IO")
        change_alpha_env = os.getenv("FORCE_QUIT_CHANGE_ALPHA")
        change_ratio_env = os.getenv("FORCE_QUIT_CHANGE_RATIO")
        change_std_mult_env = os.getenv("FORCE_QUIT_CHANGE_STD_MULT")
        change_mad_mult_env = os.getenv("FORCE_QUIT_CHANGE_MAD_MULT")
        change_decay_env = os.getenv("FORCE_QUIT_CHANGE_DECAY")
        warn_cpu_env = os.getenv("FORCE_QUIT_WARN_CPU")
        warn_mem_env = os.getenv("FORCE_QUIT_WARN_MEM")
        warn_io_env = os.getenv("FORCE_QUIT_WARN_IO")
        slow_ratio_env = os.getenv("FORCE_QUIT_SLOW_RATIO")
        fast_ratio_env = os.getenv("FORCE_QUIT_FAST_RATIO")
        ratio_window_env = os.getenv("FORCE_QUIT_RATIO_WINDOW")
        trend_window_env = os.getenv("FORCE_QUIT_TREND_WINDOW")
        trend_cpu_env = os.getenv("FORCE_QUIT_TREND_CPU")
        trend_mem_env = os.getenv("FORCE_QUIT_TREND_MEM")
        trend_io_env = os.getenv("FORCE_QUIT_TREND_IO")
        trend_io_window_env = os.getenv("FORCE_QUIT_TREND_IO_WINDOW")
        trend_slow_ratio_env = os.getenv("FORCE_QUIT_TREND_SLOW_RATIO")
        trend_fast_ratio_env = os.getenv("FORCE_QUIT_TREND_FAST_RATIO")
        show_trends_env = os.getenv("FORCE_QUIT_SHOW_TRENDS")
        show_stable_env = os.getenv("FORCE_QUIT_SHOW_STABLE")
        show_normal_env = os.getenv("FORCE_QUIT_SHOW_NORMAL")
        show_score_env = os.getenv("FORCE_QUIT_SHOW_SCORE")
        normal_window_env = os.getenv("FORCE_QUIT_NORMAL_WINDOW")
        ignore_age_env = os.getenv("FORCE_QUIT_IGNORE_AGE")
        batch_size_env = os.getenv("FORCE_QUIT_BATCH_SIZE")
        auto_batch_env = os.getenv("FORCE_QUIT_AUTO_BATCH")
        min_batch_env = os.getenv("FORCE_QUIT_MIN_BATCH")
        max_batch_env = os.getenv("FORCE_QUIT_MAX_BATCH")
        min_interval_env = os.getenv("FORCE_QUIT_MIN_INTERVAL")
        max_interval_env = os.getenv("FORCE_QUIT_MAX_INTERVAL")
        auto_env = os.getenv("FORCE_QUIT_AUTO_KILL", "").lower()

        workers = int(worker_env) if worker_env and worker_env.isdigit() else None
        min_workers = (
            int(min_workers_env)
            if min_workers_env and min_workers_env.isdigit()
            else int(cfg.get("force_quit_min_workers", 2))
        )
        max_workers = (
            int(max_workers_env)
            if max_workers_env and max_workers_env.isdigit()
            else int(cfg.get("force_quit_max_workers", 16))
        )
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
        stable_cycles = (
            int(stable_cycles_env)
            if stable_cycles_env and stable_cycles_env.isdigit()
            else int(cfg.get("force_quit_stable_cycles", 10))
        )
        stable_skip = (
            int(stable_skip_env)
            if stable_skip_env and stable_skip_env.isdigit()
            else int(cfg.get("force_quit_stable_skip", 3))
        )
        batch_size = (
            int(batch_size_env)
            if batch_size_env and batch_size_env.isdigit()
            else int(cfg.get("force_quit_batch_size", 100))
        )
        auto_batch = (
            auto_batch_env.lower() in {"1", "true", "yes"}
            if auto_batch_env
            else bool(cfg.get("force_quit_auto_batch", True))
        )
        min_batch = (
            int(min_batch_env)
            if min_batch_env and min_batch_env.isdigit()
            else int(cfg.get("force_quit_min_batch", 25))
        )
        max_batch = (
            int(max_batch_env)
            if max_batch_env and max_batch_env.isdigit()
            else int(cfg.get("force_quit_max_batch", 1000))
        )
        self.min_interval = (
            float(min_interval_env)
            if min_interval_env
            else float(cfg.get("force_quit_min_interval", 0.5))
        )
        self.max_interval = (
            float(max_interval_env)
            if max_interval_env
            else float(cfg.get("force_quit_max_interval", 10.0))
        )
        if exclude_users_env:
            exclude_users = {
                u.strip().lower() for u in exclude_users_env.split(",") if u.strip()
            }
        else:
            exclude_users = {u.lower() for u in cfg.get("force_quit_exclude_users", [])}
        ignore_names_env = os.getenv("FORCE_QUIT_IGNORE_NAMES")
        if ignore_names_env:
            ignore_names = {
                n.strip().lower() for n in ignore_names_env.split(",") if n.strip()
            }
        else:
            ignore_names = {n.lower() for n in cfg.get("force_quit_ignore_names", [])}
        slow_ratio = (
            float(slow_ratio_env)
            if slow_ratio_env
            else float(cfg.get("force_quit_slow_ratio", 0.02))
        )
        fast_ratio = (
            float(fast_ratio_env)
            if fast_ratio_env
            else float(cfg.get("force_quit_fast_ratio", 0.2))
        )
        ratio_window = (
            int(ratio_window_env)
            if ratio_window_env and ratio_window_env.isdigit()
            else int(cfg.get("force_quit_ratio_window", 5))
        )
        trend_window = (
            int(trend_window_env)
            if trend_window_env and trend_window_env.isdigit()
            else int(cfg.get("force_quit_trend_window", 5))
        )
        trend_cpu = (
            float(trend_cpu_env)
            if trend_cpu_env
            else float(cfg.get("force_quit_trend_cpu", 5.0))
        )
        trend_mem = (
            float(trend_mem_env)
            if trend_mem_env
            else float(cfg.get("force_quit_trend_mem", 50.0))
        )
        trend_io = (
            float(trend_io_env)
            if trend_io_env
            else float(cfg.get("force_quit_trend_io", 1.0))
        )
        trend_io_window = (
            int(trend_io_window_env)
            if trend_io_window_env and trend_io_window_env.isdigit()
            else int(cfg.get("force_quit_trend_io_window", trend_window))
        )
        trend_slow_ratio = (
            float(trend_slow_ratio_env)
            if trend_slow_ratio_env
            else float(cfg.get("force_quit_trend_slow_ratio", 0.05))
        )
        trend_fast_ratio = (
            float(trend_fast_ratio_env)
            if trend_fast_ratio_env
            else float(cfg.get("force_quit_trend_fast_ratio", 0.25))
        )
        self.ratio_window = ratio_window
        self.trend_window = trend_window
        self.trend_cpu = trend_cpu
        self.trend_mem = trend_mem
        self.trend_io = trend_io
        self.trend_io_window = trend_io_window
        self.trend_slow_ratio = trend_slow_ratio
        self.trend_fast_ratio = trend_fast_ratio
        self.change_window = (
            int(change_window_env)
            if change_window_env and change_window_env.isdigit()
            else int(cfg.get("force_quit_change_window", 3))
        )
        self.change_agg = (
            int(change_agg_env)
            if change_agg_env and change_agg_env.isdigit()
            else int(cfg.get("force_quit_change_agg", 1))
        )
        ProcessEntry.change_agg_window = self.change_agg
        self.change_score = (
            float(change_score_env)
            if change_score_env
            else float(cfg.get("force_quit_change_score", 1.0))
        )
        ProcessEntry.change_score_threshold = self.change_score
        self.change_cpu = (
            float(change_cpu_env)
            if change_cpu_env
            else float(cfg.get("force_quit_change_cpu", 0.5))
        )
        self.change_mem = (
            float(change_mem_env)
            if change_mem_env
            else float(cfg.get("force_quit_change_mem", 1.0))
        )
        self.change_io = (
            float(change_io_env)
            if change_io_env
            else float(cfg.get("force_quit_change_io", 0.5))
        )
        self.change_alpha = (
            float(change_alpha_env)
            if change_alpha_env
            else float(cfg.get("force_quit_change_alpha", 0.2))
        )
        self.change_ratio = (
            float(change_ratio_env)
            if change_ratio_env
            else float(cfg.get("force_quit_change_ratio", 0.3))
        )
        self.change_std_mult = (
            float(change_std_mult_env)
            if change_std_mult_env
            else float(cfg.get("force_quit_change_std_mult", 2.0))
        )
        self.change_mad_mult = (
            float(change_mad_mult_env)
            if change_mad_mult_env
            else float(cfg.get("force_quit_change_mad_mult", 3.0))
        )
        self.change_decay = (
            float(change_decay_env)
            if change_decay_env
            else float(cfg.get("force_quit_change_decay", 0.8))
        )
        ProcessEntry.cpu_threshold = self.change_cpu
        ProcessEntry.mem_threshold = self.change_mem
        ProcessEntry.io_threshold = self.change_io
        ProcessEntry.change_alpha = self.change_alpha
        ProcessEntry.change_ratio = self.change_ratio
        ProcessEntry.change_std_mult = self.change_std_mult
        ProcessEntry.change_mad_mult = self.change_mad_mult
        ProcessEntry.change_decay = self.change_decay
        self.visible_cpu = (
            float(visible_cpu_env)
            if visible_cpu_env
            else float(cfg.get("force_quit_visible_cpu", 0.5))
        )
        self.visible_mem = (
            float(visible_mem_env)
            if visible_mem_env
            else float(cfg.get("force_quit_visible_mem", 10.0))
        )
        self.visible_io = (
            float(visible_io_env)
            if visible_io_env
            else float(cfg.get("force_quit_visible_io", 0.1))
        )
        self.visible_auto = (
            visible_auto_env.lower() in {"1", "true", "yes"}
            if visible_auto_env is not None
            else bool(cfg.get("force_quit_visible_auto", False))
        )
        self.warn_cpu = (
            float(warn_cpu_env)
            if warn_cpu_env
            else float(cfg.get("force_quit_warn_cpu", 40.0))
        )
        self.warn_mem = (
            float(warn_mem_env)
            if warn_mem_env
            else float(cfg.get("force_quit_warn_mem", 200.0))
        )
        self.warn_io = (
            float(warn_io_env)
            if warn_io_env
            else float(cfg.get("force_quit_warn_io", 1.0))
        )
        self.show_deltas = (
            show_deltas_env.lower() in {"1", "true", "yes"}
            if show_deltas_env is not None
            else bool(cfg.get("force_quit_show_deltas", True))
        )
        self.hide_system = (
            hide_system_env.lower() in {"1", "true", "yes"}
            if hide_system_env is not None
            else bool(cfg.get("force_quit_hide_system", False))
        )
        self.show_trends = (
            show_trends_env.lower() in {"1", "true", "yes"}
            if show_trends_env is not None
            else bool(cfg.get("force_quit_show_trends", True))
        )
        self.show_stable = (
            show_stable_env.lower() in {"1", "true", "yes"}
            if show_stable_env is not None
            else bool(cfg.get("force_quit_show_stable", False))
        )
        self.show_normal = (
            show_normal_env.lower() in {"1", "true", "yes"}
            if show_normal_env is not None
            else bool(cfg.get("force_quit_show_normal", False))
        )
        self.show_score = (
            show_score_env.lower() in {"1", "true", "yes"}
            if show_score_env is not None
            else bool(cfg.get("force_quit_show_score", False))
        )
        self.ignore_age = (
            float(ignore_age_env)
            if ignore_age_env
            else float(cfg.get("force_quit_ignore_age", 1.0))
        )
        self.normal_window = (
            int(normal_window_env)
            if normal_window_env and normal_window_env.isdigit()
            else int(cfg.get("force_quit_normal_window", 3))
        )
        self.exclude_users = exclude_users
        self.ignore_names = ignore_names
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
        if auto_interval_env is not None:
            self.adaptive_refresh = auto_interval_env.lower() in {"1", "true", "yes"}
        elif adaptive_env is not None:
            self.adaptive_refresh = adaptive_env.lower() in {"1", "true", "yes"}
        else:
            self.adaptive_refresh = bool(
                cfg.get(
                    "force_quit_auto_interval", cfg.get("force_quit_adaptive", True)
                )
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
            "cpu" in auto_env or "both" in auto_env or auto_setting in ("cpu", "both")
        )
        self.auto_kill_mem = (
            "mem" in auto_env or "both" in auto_env or auto_setting in ("mem", "both")
        )
        self._watcher = ProcessWatcher(
            self._queue,
            interval=interval,
            detail_interval=detail,
            max_workers=workers,
            min_workers=min_workers,
            max_worker_limit=max_workers,
            sample_size=samples,
            limit=self.max_processes,
            adaptive=self.adaptive_refresh,
            adaptive_detail=self.adaptive_detail,
            conn_interval=conn_interval,
            file_interval=file_interval,
            cache_ttl=cache_ttl,
            conn_global_threshold=conn_global,
            file_global_threshold=file_global,
            stable_cycles=stable_cycles,
            stable_skip=stable_skip,
            slow_ratio=slow_ratio,
            fast_ratio=fast_ratio,
            ratio_window=ratio_window,
            trend_window=trend_window,
            trend_cpu=trend_cpu,
            trend_mem=trend_mem,
            trend_io=self.trend_io,
            trend_io_window=self.trend_io_window,
            trend_slow_ratio=self.trend_slow_ratio,
            trend_fast_ratio=self.trend_fast_ratio,
            hide_system=self.hide_system,
            exclude_users=self.exclude_users,
            ignore_names=ignore_names,
            normal_window=self.normal_window,
            visible_cpu=self.visible_cpu,
            visible_mem=self.visible_mem,
            visible_io=self.visible_io,
            visible_auto=self.visible_auto,
            warn_cpu=self.warn_cpu,
            warn_mem=self.warn_mem,
            warn_io=self.warn_io,
            cpu_alert=self.cpu_alert,
            mem_alert=self.mem_alert,
            ignore_age=self.ignore_age,
            change_alpha=self.change_alpha,
            change_ratio=self.change_ratio,
            change_mad_mult=self.change_mad_mult,
            change_decay=self.change_decay,
            batch_size=batch_size,
            auto_batch=auto_batch,
            min_batch_size=min_batch,
            max_batch_size=max_batch,
            min_interval=self.min_interval,
            max_interval=self.max_interval,
        )
        self._watcher.start()

        container = self.create_container()
        self.add_title(container, "Force Quit Running Processes")

        self.tabview = ctk.CTkTabview(container)
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
        ]
        if has_active_window_support():
            actions.append(("Kill Active Window", self._kill_active_window))
        if has_cursor_window_support():
            actions.append(("Kill by Click", self._kill_by_click))
            actions.append(("Calibrate Click", self._calibrate_click_interval))
        actions.append(("Kill Zombies", self._kill_zombies))
        self._action_buttons: list[ctk.CTkButton] = []
        for i, (text, cmd) in enumerate(actions):
            btn = ctk.CTkButton(actions_scroll, text=text, command=cmd, state=tk.DISABLED)
            btn.grid(row=i // 2, column=i % 2, padx=5, pady=5, sticky="ew")
            self.add_tooltip(btn, "Force terminate matching processes")
            self._action_buttons.append(btn)
        actions_scroll.grid_columnconfigure(0, weight=1)
        actions_scroll.grid_columnconfigure(1, weight=1)

        search_frame = ctk.CTkFrame(monitor_tab, fg_color="transparent")
        search_frame.pack(fill="x", padx=10)
        self.search_var = ctk.StringVar()
        entry = ctk.CTkEntry(search_frame, textvariable=self.search_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<KeyRelease>", lambda _e: self._populate())
        self.add_tooltip(entry, "Filter processes by text")

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
                "Score ≥",
                "Changed",
                "Trending",
                "Stable",
                "Normal",
                "Status",
                "Level",
            ],
            command=lambda _v: self._populate(),
        )
        filter_menu.pack(side="left", padx=5)
        self.add_tooltip(filter_menu, "Choose filter field")

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
                "Level",
                "Score",
            ],
            command=lambda _v: self._populate(),
        )
        sort_menu.pack(side="left", padx=5)
        self.add_tooltip(sort_menu, "Sort processes")

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
        ctk.CTkLabel(options_frame, text="CPU ≥", font=self.font).pack(side="left")
        ctk.CTkEntry(options_frame, width=60, textvariable=self.cpu_alert_var).pack(
            side="left", padx=5
        )
        ctk.CTkCheckBox(
            options_frame,
            text="Auto Kill CPU",
            variable=self.auto_cpu_var,
            command=lambda: setattr(self, "auto_kill_cpu", self.auto_cpu_var.get()),
        ).pack(side="left", padx=5)
        ctk.CTkLabel(options_frame, text="Mem ≥ MB", font=self.font).pack(
            side="left", padx=(10, 0)
        )
        ctk.CTkEntry(options_frame, width=60, textvariable=self.mem_alert_var).pack(
            side="left", padx=5
        )
        ctk.CTkCheckBox(
            options_frame,
            text="Auto Kill Mem",
            variable=self.auto_mem_var,
            command=lambda: setattr(self, "auto_kill_mem", self.auto_mem_var.get()),
        ).pack(side="left", padx=5)
        ctk.CTkButton(options_frame, text="Apply", command=self._apply_thresholds).pack(
            side="left", padx=5
        )
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
            command=lambda: self._toggle_adaptive_detail(
                self.adaptive_detail_var.get()
            ),
        ).pack(side="left", padx=5)

        self.tree_frame = ctk.CTkFrame(monitor_tab)
        self.tree_frame.pack(fill="both", expand=True, padx=10, pady=10)
        columns = [
            "PID",
            "User",
            "Name",
            "Level",
        ]
        if self.show_score:
            columns.append("Score")
        columns += [
            "CPU",
            "Avg CPU",
            "Mem",
            "IO",
            "Avg IO",
        ]
        if self.show_deltas:
            columns.extend(["\u0394CPU", "\u0394Mem", "\u0394IO"])
        columns += [
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
        hsb = ttk.Scrollbar(
            self.tree_frame, orient="horizontal", command=self.tree.xview
        )
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree_frame.grid_rowconfigure(0, weight=1)
        self.tree_frame.grid_columnconfigure(0, weight=1)
        self.empty_label = ctk.CTkLabel(self.tree_frame, text="No processes found")
        self.empty_label.grid(row=0, column=0)
        self.empty_label.grid_remove()
        for col in columns:
            self.tree.heading(
                col, text=col, command=lambda c=col: self._sort_by_column(c)
            )
            narrow = {
                "PID",
                "CPU",
                "Mem",
                "Avg CPU",
                "Avg IO",
                "Score",
                "\u0394CPU",
                "\u0394Mem",
                "\u0394IO",
            }
            width = 60 if col in narrow else 90
            self.tree.column(col, width=width, anchor="w")
        default_col = self.sort_var.get()
        self.tree.heading(default_col, text=default_col + " \u25bc")
        self.tree.tag_configure("high_cpu", background="#ffdddd")
        self.tree.tag_configure("high_mem", background="#fff5cc")
        self.tree.tag_configure("changed", background="#e6f7ff")
        self.tree.tag_configure("trending", background="#ffe6cc")
        self.tree.tag_configure("stable", background="#f5f5f5")
        self.tree.tag_configure("warning", background="#fff5cc")
        self.tree.tag_configure("critical", background="#ffcccc")
        hover_env = os.getenv("FORCE_QUIT_HOVER_COLOR")
        if hover_env:
            self.hover_color = hover_env
        else:
            bright = hex_brightness(self.accent)
            if bright < 0.3:
                factor = 0.6
            elif bright < 0.6:
                factor = 0.4
            else:
                factor = 0.2
            if bright < 0.5:
                self.hover_color = lighten_color(self.accent, factor)
            else:
                self.hover_color = darken_color(self.accent, factor)
        self.tree.tag_configure("hover", background=self.hover_color)
        self._hover_iid: str | None = None
        self._last_motion: tuple[int, int] | None = None
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_selection)
        self.tree.bind("<Motion>", self._on_hover)
        self.tree.bind("<Leave>", self._on_tree_leave)

        self.details_frame = ctk.CTkFrame(monitor_tab)
        self.details_frame.pack(fill="both", padx=10, pady=(5, 0))
        self.details_text = ctk.CTkTextbox(self.details_frame, height=120)
        self.details_text.pack(fill="both", expand=True)
        self.details_text.configure(state="disabled")
        self._toggle_details()

        self.kill_selected_btn = ctk.CTkButton(
            monitor_tab,
            text="Force Quit Selected",
            command=self._kill_selected,
            state=tk.DISABLED,
        )
        self.kill_selected_btn.pack(pady=(5, 0))

        self.status_var = ctk.StringVar(value="0 processes")
        ctk.CTkLabel(monitor_tab, textvariable=self.status_var, font=self.font).pack(
            pady=(0, 5)
        )

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.center_window()

        # Apply current styling
        self.refresh_fonts()
        self.refresh_theme()

        self._auto_refresh()

    def _drain_queue(self) -> None:
        changed = False
        while not self._queue.empty():
            updates, removed, progress = self._queue.get_nowait()
            self._enum_progress = progress
            if updates or removed:
                changed = True
            self.process_snapshot.update(updates)
            for pid in removed:
                self.process_snapshot.pop(pid, None)
                self._changed_tags.pop(pid, None)
        if changed:
            self._snapshot_changed = True

    def _update_kill_actions(self) -> None:
        """Enable kill actions once process data is available.

        Previously the dialog waited for the initial process enumeration to
        fully complete (``_enum_progress`` reaching ``1.0``) before enabling the
        various kill buttons.  On systems with a large number of processes this
        could take a noticeable amount of time, leaving the actions appearing
        unresponsive.  Instead we now enable the buttons as soon as *any*
        process data has been loaded.  The old behaviour is still respected if
        enumeration completes with an empty snapshot.
        """

        if self._actions_enabled:
            return
        if self._enum_progress < 1.0 and not self.process_snapshot:
            return
        self.kill_selected_btn.configure(state=tk.NORMAL)
        for btn in self._action_buttons:
            btn.configure(state=tk.NORMAL)
        self._actions_enabled = True

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
        if not psutil.pid_exists(pid):
            return True
        if kill_process(pid, timeout=timeout):
            return True
        if not psutil.pid_exists(pid):
            return True
        # escalate to killing the entire tree if the direct kill failed
        if kill_process_tree(pid, timeout=timeout):
            return True
        if not psutil.pid_exists(pid):
            return True
        info = {"pid": pid, "exists": psutil.pid_exists(pid)}
        try:
            proc = psutil.Process(pid)
            info.update({"name": proc.name(), "status": proc.status()})
        except Exception as exc:  # pragma: no cover - diagnostic path
            info["error"] = repr(exc)
        msg = "force_kill failed"
        data = json.dumps(info, indent=2, default=str)
        logger.error("%s: %s", msg, data)
        print(f"{msg}: {data}", file=sys.stderr)
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
    def _get_active_window() -> WindowInfo:
        """Return information about the currently active window."""
        return get_active_window()

    @staticmethod
    def _get_active_window_pid() -> int | None:
        """Return the PID owning the currently active window if available."""
        return ForceQuitDialog._get_active_window().pid

    @staticmethod
    def _get_window_under_cursor() -> WindowInfo:
        """Return information about the window under the mouse cursor."""
        return get_window_under_cursor()

    @classmethod
    def force_kill_window_under_cursor(cls) -> bool:
        """Force kill the process owning the window currently under the cursor."""
        info = cls._get_window_under_cursor()
        if info.pid is None or info.pid == os.getpid():
            return False
        return cls.force_kill(info.pid)

    @classmethod
    def force_kill_active_window(cls) -> bool:
        """Force terminate the process owning the active window."""
        pid = cls._get_active_window_pid()
        if pid is None or pid == os.getpid():
            return False
        return cls.force_kill(pid)

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
        exclude: set[int]
        if exclude_self:
            exclude = {os.getpid(), os.getppid()}
        else:
            exclude = set()
        pids: list[int] = []
        for proc in psutil.process_iter(["pid", "exe"]):
            if proc.pid in exclude:
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
    def force_kill_above_io(cls, threshold_mb: float, interval: float = 1.0) -> int:
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
                    (io.read_bytes + io.write_bytes - prev) / interval / (1024 * 1024)
                )
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
                if proc.pid == os.getpid() or proc.pid < 1000:
                    continue
                if hasattr(proc, "net_connections"):
                    conns = proc.net_connections(kind="inet")
                else:  # pragma: no cover - psutil<6
                    conns = proc.connections(kind="inet")
                if len(conns) > threshold:
                    pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return cls.force_kill_multiple(pids)

    @classmethod
    def force_kill_sustained_cpu(cls, threshold: float, duration: float = 1.0) -> int:
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
                cpu = (
                    (sum(proc.cpu_times()) - start)
                    / duration
                    / psutil.cpu_count()
                    * 100
                )
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
        self._debounce_id = self.after(100, self._apply_filter_sort)

    def _current_filter_key(self) -> tuple[str, str, str, bool]:
        return (
            self.search_var.get().lower(),
            self.filter_var.get(),
            self.sort_var.get(),
            self.sort_reverse,
        )

    def is_normal(self, entry: ProcessEntry) -> bool:
        return entry.normal

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
            elif filter_by == "Score ≥":
                try:
                    threshold = float(query)
                except ValueError:
                    processes = []
                else:
                    processes = [p for p in processes if p.last_score >= threshold]
            elif filter_by == "Changed":
                processes = [p for p in processes if self._changed_tags.get(p.pid, 0)]
            elif filter_by == "Trending":
                processes = [
                    p
                    for p in processes
                    if p.trending_cpu or p.trending_mem or p.trending_io
                ]
            elif filter_by == "Stable":
                processes = [p for p in processes if p.stable]
            elif filter_by == "Normal":
                processes = [p for p in processes if self.is_normal(p)]
            elif filter_by == "Status":
                processes = [p for p in processes if query in p.status.lower()]
            elif filter_by == "Level":
                processes = [p for p in processes if p.level.lower().startswith(query)]
            else:
                processes = []
        else:
            main = [p for p in processes if not self.is_normal(p)]
            if self.show_normal:
                normal = [p for p in processes if self.is_normal(p)]
                processes = main + normal
            else:
                processes = main

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
            "Level": lambda p: {"normal": 0, "warning": 1, "critical": 2}[p.level],
            "Score": lambda p: p.last_score,
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
                base_values = [
                    entry.pid,
                    (entry.user or "")[:8],
                    entry.name,
                    entry.level,
                ]
                if self.show_score:
                    base_values.append(f"{entry.last_score:.2f}")
                base_values.extend(
                    [
                        f"{entry.cpu:.1f}",
                        f"{entry.avg_cpu:.1f}",
                        f"{entry.mem:.1f}",
                        f"{entry.io_rate:.1f}",
                        f"{entry.avg_io:.1f}",
                    ]
                )
                if self.show_deltas:
                    base_values.extend(
                        [
                            f"{entry.delta_cpu:+.1f}",
                            f"{entry.delta_mem:+.1f}",
                            f"{entry.delta_io:+.1f}",
                        ]
                    )
                base_values.extend(
                    [
                        entry.threads,
                        entry.files,
                        entry.conns,
                        entry.status[:6],
                        age,
                    ]
                )
                values = tuple(base_values)
                tags: list[str] = []
                if entry.changed:
                    self._changed_tags[entry.pid] = self.change_window
                elif entry.pid in self._changed_tags:
                    self._changed_tags[entry.pid] -= 1
                    if self._changed_tags[entry.pid] <= 0:
                        self._changed_tags.pop(entry.pid, None)
                if self._changed_tags.get(entry.pid, 0):
                    tags.append("changed")
                if entry.cpu >= self.cpu_alert or entry.avg_cpu >= self.cpu_alert:
                    tags.append("high_cpu")
                if entry.mem >= self.mem_alert:
                    tags.append("high_mem")
                if entry.level == "critical":
                    tags.append("critical")
                elif entry.level == "warning":
                    tags.append("warning")
                if self.show_trends and (
                    entry.trending_cpu or entry.trending_mem or entry.trending_io
                ):
                    tags.append("trending")
                if self.show_stable and entry.stable:
                    tags.append("stable")
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
                    self._changed_tags.pop(int(iid), None)
                except ValueError:
                    pass

        self.after_idle(update_tree)
        self.after_idle(self._update_hover)
        self._update_status(len(processes))
        if processes:
            if self.empty_label.winfo_ismapped():
                self.empty_label.grid_remove()
        else:
            self.empty_label.lift()
            self.empty_label.grid()

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
                        "level",
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
                            entry.level,
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
        menu.add_command(
            label="Terminate", command=lambda pid=int(iid): self._confirm_kill(pid)
        )
        menu.post(event.x_root, event.y_root)

    def _sort_by_column(self, col: str) -> None:
        current = self.sort_var.get()
        if col == current:
            self.sort_reverse = not self.sort_reverse
        else:
            self.tree.heading(current, text=current)
            self.sort_var.set(col)
            self.sort_reverse = True
        arrow = " \u25bc" if self.sort_reverse else " \u25b2"
        self.tree.heading(col, text=col + arrow)
        self._populate()

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        self.pause_btn.configure(text="Resume" if self.paused else "Pause")
        if self.paused:
            self._safe_pause()
        else:
            self._safe_resume()
            self._auto_refresh()

    def _safe_pause(self) -> None:
        try:
            self._watcher.pause()
        except Exception:
            pass

    def _safe_resume(self) -> None:
        try:
            self._watcher.resume()
        except Exception:
            pass

    def _toggle_adaptive(self, enabled: bool) -> None:
        """Enable or disable adaptive refresh."""
        self.adaptive_refresh = enabled
        self._watcher.adaptive = enabled

    def _toggle_adaptive_detail(self, enabled: bool) -> None:
        """Enable or disable adaptive detail refresh."""
        self.adaptive_detail = enabled
        self._watcher.adaptive_detail = enabled

    def _update_status(self, count: int) -> None:
        if self._enum_progress < 1.0:
            self.status_var.set(
                f"Enumerating processes: {int(self._enum_progress * 100)}%"
            )
            return
        selected = len(self.tree.selection())
        total_cpu = sum(p.cpu for p in self.process_snapshot.values())
        total_mem = sum(p.mem for p in self.process_snapshot.values())
        total = self._watcher.process_count
        trend = self._watcher.recent_trend_ratio * 100
        changed = self._watcher.recent_change_ratio * 100
        batch = self._watcher.batch_size
        avg_batch = self._watcher.average_batch_size
        avg_cycle = self._watcher.average_cycle_time
        avg_interval = self._watcher.average_interval
        workers = self._watcher.worker_count
        throughput = self._watcher.average_throughput
        self.status_var.set(
            f"{count}/{total} processes ({selected} selected) | CPU {total_cpu:.1f}% | "
            f"Mem {total_mem:.1f} MB | Trending {trend:.0f}% | Changed {changed:.0f}% | "
            f"Batch {batch} (avg {avg_batch:.0f}) | Cycle {avg_cycle:.2f}s | Int {avg_interval:.2f}s | "
            f"Thr {throughput:.0f}/s | Workers {workers}"
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

    def _apply_hover_tag(self) -> None:
        if self._hover_iid and self.tree.exists(self._hover_iid):
            tags = set(self.tree.item(self._hover_iid, "tags"))
            tags.add("hover")
            self.tree.item(self._hover_iid, tags=tuple(tags))

    def _remove_hover_tag(self) -> None:
        if self._hover_iid and self.tree.exists(self._hover_iid):
            tags = set(self.tree.item(self._hover_iid, "tags"))
            tags.discard("hover")
            self.tree.item(self._hover_iid, tags=tuple(tags))

    def _set_hover_row(self, iid: str | None) -> None:
        if iid == self._hover_iid:
            if iid is not None and not self.tree.exists(iid):
                self._hover_iid = None
            return
        self._remove_hover_tag()
        if iid is not None and not self.tree.exists(iid):
            iid = None
        self._hover_iid = iid
        self._apply_hover_tag()

    def _on_hover(self, event) -> None:
        if event.widget is not self.tree:
            return
        self._last_motion = (event.x, event.y)
        iid = self.tree.identify_row(event.y)
        self._set_hover_row(iid)

    def _on_tree_leave(self, _event) -> None:
        self._last_motion = None
        self._set_hover_row(None)

    def _update_hover(self) -> None:
        if not self._last_motion:
            self._set_hover_row(None)
            return
        _, y = self._last_motion
        iid = self.tree.identify_row(y)
        self._set_hover_row(iid)

    def _highlight_pid(self, pid: int | None, _title: str | None = None) -> None:
        """Highlight ``pid`` in the process list while the overlay is active."""
        if not hasattr(self, "tree"):
            return
        if pid is None or not self.tree.exists(str(pid)):
            self.tree.selection_remove(self.tree.selection())
            self._set_hover_row(None)
            return
        iid = str(pid)
        current = self.tree.selection()
        if current != (iid,):
            self.tree.see(iid)
            self.tree.selection_set(iid)
            self._show_details()
        self._set_hover_row(iid)

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
                start = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(proc.create_time())
                )
                status = proc.status()
                mem = proc.memory_info().rss / (1024 * 1024)
                cpu = proc.cpu_percent(interval=0.1)
                threads = proc.num_threads()
                files = len(proc.open_files())
                if hasattr(proc, "net_connections"):
                    conns = len(proc.net_connections(kind="inet"))
                else:  # pragma: no cover - psutil<6
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
            "Force Quit",
            f"Terminated {count} process(es) using port {port}",
            parent=self,
        )
        self._populate()

    def _kill_by_host(self) -> None:
        host = self.search_var.get().strip()
        if not host:
            messagebox.showerror("Force Quit", "Enter a hostname or IP", parent=self)
            return
        count = self.force_kill_by_host(host)
        messagebox.showinfo(
            "Force Quit",
            f"Terminated {count} process(es) connected to {host}",
            parent=self,
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
            messagebox.showerror(
                "Force Quit", "Enter a command line regex", parent=self
            )
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
            "Force Quit",
            f"Terminated {count} process(es) above {threshold}% CPU",
            parent=self,
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

    def _kill_active_window(self) -> None:
        info = self._get_active_window()
        pid = info.pid
        if pid is None:
            messagebox.showerror(
                "Force Quit", "Unable to determine active window", parent=self
            )
            return
        if not messagebox.askyesno(
            "Force Quit",
            f"Terminate {info.title or 'window'} (pid {pid})?",
            parent=self,
        ):
            return
        ok = self.force_kill(pid)
        if ok:
            messagebox.showinfo("Force Quit", f"Terminated process {pid}", parent=self)
        else:
            messagebox.showerror(
                "Force Quit", f"Failed to terminate process {pid}", parent=self
            )
        self._populate()

    def _configure_overlay(self) -> None:
        """Apply environment and configuration settings to the overlay."""
        overlay = self._overlay
        overlay.apply_defaults()
        cfg = self.app.config if hasattr(self.app, "config") else {}
        color = getattr(self, "hover_color", None) or getattr(self, "accent", "red")
        if hasattr(cfg, "get"):
            color = cfg.get("kill_by_click_highlight", color)
        color = os.getenv("KILL_BY_CLICK_HIGHLIGHT", color)
        skip_env = os.getenv("FORCE_QUIT_CLICK_SKIP_CONFIRM")
        skip_cfg = cfg.get("force_quit_click_skip_confirm") if hasattr(cfg, "get") else None
        if skip_env is not None:
            skip_confirm = skip_env.lower() not in {"0", "false", "no"}
        elif skip_cfg is not None:
            skip_confirm = bool(skip_cfg)
        else:
            skip_confirm = getattr(overlay, "skip_confirm", False)
        settings = {"color": color, "skip_confirm": skip_confirm}
        if settings != getattr(self, "_overlay_settings", None):
            overlay.on_hover = self._highlight_pid
            overlay.set_highlight_color(color)
            overlay.skip_confirm = skip_confirm
            self._overlay_settings = settings

    class _OverlayContext:
        """Context manager to manage Kill-by-Click overlay lifecycle."""

        def __init__(self, dialog: "ForceQuitDialog", overlay: ClickOverlay):
            self.dialog = dialog
            self.overlay = overlay
            self.paused = dialog.paused

        def __enter__(self) -> ClickOverlay:
            if not self.paused:
                self.dialog._safe_pause()
            self.dialog.withdraw()
            if hasattr(self.dialog, "tk"):
                self.dialog.update_idletasks()
            return self.overlay

        def __exit__(
            self,
            exc_type: Optional[type[BaseException]],
            exc: Optional[BaseException],
            tb: Optional[Any],
        ) -> bool:
            if getattr(self.overlay, "on_hover", None) is not None:
                try:
                    self.overlay.on_hover(None, None)
                except Exception:
                    pass
            try:
                self.overlay.reset()
            finally:
                self.dialog.deiconify()
                if not self.paused:
                    self.dialog._safe_resume()
                self.dialog.after_idle(self.dialog._update_hover)
            return False

    def _kill_by_click(self) -> None:
        """Launch the click-to-kill overlay without blocking the UI."""
        if self._overlay_thread and self._overlay_thread.is_alive():
            return
        overlay = self._overlay
        ctx = self._OverlayContext(self, overlay)
        self._overlay_ctx = ctx
        thread: threading.Thread | None = None
        try:
            ctx.__enter__()

            done = threading.Event()
            self._overlay_done = done
            holder: dict[str, Any] = {}

            def invoke_choose() -> None:
                if done.is_set():
                    return
                try:
                    holder["res"] = overlay.choose()
                except Exception as exc:  # pragma: no cover - defensive
                    holder["res"] = exc
                finally:
                    done.set()

            def run() -> None:
                # Run the blocking Tk call on the UI thread
                self.after(0, invoke_choose)
                done.wait()
                res = holder.get("res", (None, None))
                if isinstance(res, tuple):
                    pid, title = res
                    ctime: float | None = None
                    cmd: tuple[str, ...] | None = None
                    exe: str | None = None
                    if pid is not None:
                        try:
                            proc = psutil.Process(pid)
                            ctime = proc.create_time()
                            cmd = tuple(proc.cmdline())
                            exe = proc.exe()
                        except psutil.Error:
                            pass
                    result: tuple[
                        int | None,
                        str | None,
                        float | None,
                        tuple[str, ...] | None,
                        str | None,
                    ] | Exception = (
                        pid,
                        title,
                        ctime,
                        cmd,
                        exe,
                    )
                else:
                    result = res
                if self._overlay_thread:
                    self.after(0, lambda: self._finish_kill_by_click(ctx, result))

            overlay.reset_watchdog()
            thread = threading.Thread(target=run, daemon=True)
            self._overlay_thread = thread
            thread.start()
        except Exception:
            logger.exception("Failed to start overlay")
            raise
        finally:
            if (thread is None or not thread.is_alive()) and self._overlay_ctx is ctx:
                try:
                    ctx.__exit__(*sys.exc_info())
                except Exception:  # pragma: no cover - best effort cleanup
                    logger.exception("Error during overlay cleanup")
                self._overlay_ctx = None

        if not (thread and thread.is_alive()):
            return
        if self.app.config.get("developer_mode", False):
            fd, path = tempfile.mkstemp()
            os.close(fd)
            Path(path).touch()
            watchdog_script = Path(__file__).resolve().parents[1] / "utils" / "force_quit_watchdog.py"
            self._overlay_last_ping_file = path
            self._overlay_watchdog_proc = subprocess.Popen(
                [sys.executable, str(watchdog_script), path, str(KILL_BY_CLICK_WATCHDOG), str(KILL_BY_CLICK_WATCHDOG_MISSES)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            self._overlay_sync = threading.Thread(
                target=self._sync_watchdog_ping_file, daemon=True
            )
            self._overlay_sync.start()
            self._overlay_poller = threading.Thread(
                target=self._poll_watchdog_output, args=(ctx,), daemon=True
            )
            self._overlay_poller.start()
        else:
            self._overlay_watchdog_proc = None
            self._overlay_last_ping_file = None
            self._overlay_sync = None
            self._overlay_poller = None

    def _sync_watchdog_ping_file(self) -> None:
        last = 0.0
        while True:
            thread = self._overlay_thread
            path = self._overlay_last_ping_file
            if not (thread and thread.is_alive() and path):
                break
            current = getattr(self._overlay, "_last_ping", 0.0)
            if current != last:
                try:
                    os.utime(path, None)
                except OSError:
                    pass
                last = current
            time.sleep(0.05)

    def _overlay_info(self, overlay: "ClickOverlay") -> dict[str, Any]:
        """Return diagnostic info about the overlay state."""

        def _safe(name: str) -> Any:
            val = getattr(overlay, name, None)
            return None if isinstance(val, Mock) else val

        last = _safe("_last_ping") or 0.0
        misses = _safe("_watchdog_misses") or 0
        return {
            "state": _safe("state"),
            "cursor": {"x": _safe("_cursor_x"), "y": _safe("_cursor_y")},
            "hover_pid": _safe("pid"),
            "hover_title": _safe("title_text"),
            "missed_heartbeats": misses,
            "stalled_for": round(time.monotonic() - last, 3),
        }

    def _cleanup_overlay(
        self, ctx: "ForceQuitDialog._OverlayContext | None"
    ) -> None:
        """Tear down overlay threads, files and context."""

        done = getattr(self, "_overlay_done", None)
        if done is not None:
            done.set()
            self._overlay_done = None

        thread = self._overlay_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.1)
        self._overlay_thread = None

        proc = getattr(self, "_overlay_watchdog_proc", None)
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=0.1)
            self._overlay_watchdog_proc = None

        sync = getattr(self, "_overlay_sync", None)
        if sync is not None and sync.is_alive():
            sync.join(timeout=0.1)
        self._overlay_sync = None

        poller = getattr(self, "_overlay_poller", None)
        if poller is not None and poller.is_alive():
            poller.join(timeout=0.1)
        self._overlay_poller = None

        path = getattr(self, "_overlay_last_ping_file", None)
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
        self._overlay_last_ping_file = None

        self._overlay_closed = False

        if ctx is not None and self._overlay_ctx is ctx:
            self._overlay_ctx = None
            try:
                ctx.__exit__(None, None, None)
            except Exception:
                logger.exception("Error during overlay cleanup")

    def _poll_watchdog_output(self, ctx: "ForceQuitDialog._OverlayContext") -> None:
        proc = self._overlay_watchdog_proc
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            try:
                msg = json.loads(line.strip())
            except Exception:
                continue
            overlay = self._overlay
            elapsed = msg.get("elapsed", 0.0)
            misses = msg.get("misses", 0)
            info = self._overlay_info(overlay)
            info.update(
                {
                    "timestamp": datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                    "missed_heartbeats": misses,
                    "stalled_for": round(elapsed, 3),
                    "stack": traceback.format_stack(limit=5),
                }
            )
            msg = "Kill by Click timed out"
            data = json.dumps(info, indent=2, default=str)
            logger.warning("%s: %s", msg, data)
            print(f"{msg}: {data}", file=sys.stderr)
            try:
                overlay.close()
            except Exception:
                pass
            self._overlay_thread = None
            self.after(0, lambda: self._finish_kill_by_click(ctx, TimeoutError("watchdog")))
            break

    def _finish_kill_by_click(
        self,
        ctx: "ForceQuitDialog._OverlayContext",
        result: tuple[
            int | None,
            str | None,
            float | None,
            tuple[str, ...] | None,
            str | None,
        ] | Exception,
    ) -> None:
        if ctx is not self._overlay_ctx:
            return
        overlay = self._overlay
        info = self._overlay_info(overlay)
        closed_by_cancel = getattr(self, "_overlay_closed", False)
        self._cleanup_overlay(ctx)
        if isinstance(result, Exception):
            info.update(
                {
                    "timestamp": datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                    "error": repr(result),
                    "stack": traceback.format_exception(
                        type(result), result, result.__traceback__
                    ),
                }
            )
            msg = "Kill by Click raised an exception"
            data = json.dumps(info, indent=2, default=str)
            logger.error("%s: %s", msg, data)
            print(f"{msg}: {data}", file=sys.stderr)
            return
        pid, title, ctime, cmd, exe = result
        if pid is None:
            if not closed_by_cancel:
                try:
                    overlay.close()
                except Exception:
                    pass
            info.update(
                {
                    "timestamp": datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                    "stack": traceback.format_stack(limit=5),
                }
            )
            msg = "Kill by Click failed to return a process"
            data = json.dumps(info, indent=2, default=str)
            logger.warning("%s: %s", msg, data)
            print(f"{msg}: {data}", file=sys.stderr)
            messagebox.showwarning(
                "Force Quit", "No process was selected", parent=self
            )
            self._populate()
            return
        if pid == os.getpid():
            info.update(
                {
                    "timestamp": datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                    "pid": pid,
                    "title": title,
                    "cmdline": cmd,
                    "exe": exe,
                    "stack": traceback.format_stack(limit=5),
                }
            )
            msg = "Kill by Click refused to terminate self"
            data = json.dumps(info, indent=2, default=str)
            logger.warning("%s: %s", msg, data)
            print(f"{msg}: {data}", file=sys.stderr)
            messagebox.showwarning(
                "Force Quit", "Cannot terminate this application", parent=self
            )
            self._populate()
            return

        def _target_vanished() -> None:
            diag = info.copy()
            diag.update(
                {
                    "timestamp": datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                    "pid": pid,
                    "title": title,
                    "cmdline": cmd,
                    "exe": exe,
                    "stack": traceback.format_stack(limit=5),
                }
            )
            msg = "Kill by Click target vanished"
            data = json.dumps(diag, indent=2, default=str)
            logger.warning("%s: %s", msg, data)
            print(f"{msg}: {data}", file=sys.stderr)
            messagebox.showwarning(
                "Force Quit", f"Process {pid} no longer exists", parent=self
            )
            self._populate()

        if ctime is not None or cmd is not None or exe is not None:
            try:
                proc = psutil.Process(pid)
                changed = False
                current_cmd = None
                current_exe = None
                if ctime is not None and proc.create_time() != ctime:
                    changed = True
                if cmd is not None:
                    try:
                        current_cmd = tuple(proc.cmdline())
                    except psutil.Error:
                        current_cmd = None
                    if current_cmd != cmd:
                        changed = True
                if exe is not None:
                    try:
                        current_exe = proc.exe()
                    except psutil.Error:
                        current_exe = None
                    if current_exe != exe:
                        changed = True
                if changed:
                    diag = info.copy()
                    diag.update(
                        {
                            "timestamp": datetime.now(timezone.utc)
                            .replace(microsecond=0)
                            .isoformat(),
                            "pid": pid,
                            "title": title,
                            "cmdline": cmd,
                            "exe": exe,
                            "current_cmdline": current_cmd,
                            "current_exe": current_exe,
                            "stack": traceback.format_stack(limit=5),
                        }
                    )
                    msg = "Kill by Click target changed"
                    data = json.dumps(diag, indent=2, default=str)
                    logger.warning("%s: %s", msg, data)
                    print(f"{msg}: {data}", file=sys.stderr)
                    messagebox.showwarning(
                        "Force Quit", f"Process {pid} changed", parent=self
                    )
                    self._populate()
                    return
            except psutil.Error:
                pass
        if not overlay.skip_confirm:
            if not messagebox.askyesno(
                "Force Quit", f"Terminate {title or 'window'} (pid {pid})?", parent=self
            ):
                return
        ok = self.force_kill(pid)
        if ok:
            messagebox.showinfo("Force Quit", f"Terminated process {pid}", parent=self)
        elif psutil.pid_exists(pid):
            diag = info.copy()
            diag.update(
                {
                    "pid": pid,
                    "title": title,
                    "cmdline": cmd,
                    "exe": exe,
                    "stack": traceback.format_stack(limit=5),
                }
            )
            msg = "Kill by Click could not terminate process"
            data = json.dumps(diag, indent=2, default=str)
            logger.error("%s: %s", msg, data)
            print(f"{msg}: {data}", file=sys.stderr)
            messagebox.showerror(
                "Force Quit", f"Failed to terminate process {pid}", parent=self
            )
        else:
            _target_vanished()
        self._populate()

    def cancel_kill_by_click(self) -> None:
        """Abort an in-progress Kill by Click operation."""
        thread = self._overlay_thread
        if thread and thread.is_alive():
            try:
                self._overlay_closed = True
                self._overlay.close()
            except Exception:
                pass
        ctx = getattr(self, "_overlay_ctx", None)
        self._cleanup_overlay(ctx)

    def _calibrate_click_interval(self) -> None:
        """Re-run click interval calibration."""
        interval, min_interval, max_interval = ClickOverlay.auto_tune_interval()
        cfg = self.app.config
        try:
            cfg.set("kill_by_click_interval_calibrated", interval)
            cfg.set("kill_by_click_min_interval_calibrated", min_interval)
            cfg.set("kill_by_click_max_interval_calibrated", max_interval)
            cfg.save()
        except Exception:
            try:
                cfg["kill_by_click_interval_calibrated"] = interval
                cfg["kill_by_click_min_interval_calibrated"] = min_interval
                cfg["kill_by_click_max_interval_calibrated"] = max_interval
            except Exception:
                pass
        self._overlay.interval = interval
        self._overlay.min_interval = min_interval
        self._overlay.max_interval = max_interval

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
        cfg.set("force_quit_auto_interval", self.adaptive_refresh)
        cfg.set("force_quit_adaptive_detail", self.adaptive_detail)
        cfg.save()
        self._populate()

    def _auto_refresh(self) -> None:
        if not self.winfo_exists():
            return
        if not hasattr(self, "search_var"):
            # Dialog not fully initialized yet
            self._after_id = self.after(self.frame_delay, self._auto_refresh)
            return
        if self.paused:
            self._after_id = self.after(self.frame_delay, self._auto_refresh)
            return
        self._drain_queue()
        self._update_kill_actions()
        self._update_status(len(self.tree.get_children()))
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
            interval_ms = int(float(self.interval_var.get()) * 1000)
        except Exception:
            interval_ms = int(self._watcher.interval * 1000)
        if not self.process_snapshot:
            delay = self.frame_delay
        else:
            delay = max(self.frame_delay, interval_ms)
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
        cfg.set("force_quit_auto_interval", self.adaptive_refresh)
        cfg.set("force_quit_adaptive_detail", self.adaptive_detail)
        cfg.set("force_quit_ratio_window", self._watcher._ratio_window)
        cfg.set("force_quit_trend_window", self._watcher._trend_window)
        cfg.set("force_quit_trend_cpu", self._watcher._trend_cpu)
        cfg.set("force_quit_trend_mem", self._watcher._trend_mem)
        cfg.set("force_quit_trend_io", self._watcher._trend_io)
        cfg.set("force_quit_trend_io_window", self._watcher._trend_io_window)
        cfg.set("force_quit_trend_slow_ratio", self._watcher._trend_slow_ratio)
        cfg.set("force_quit_trend_fast_ratio", self._watcher._trend_fast_ratio)
        cfg.set("force_quit_stable_cycles", self._watcher._stable_cycles)
        cfg.set("force_quit_stable_skip", self._watcher._stable_skip)
        cfg.set("force_quit_change_window", self.change_window)
        cfg.set("force_quit_change_agg", self.change_agg)
        cfg.set("force_quit_change_score", self.change_score)
        cfg.set("force_quit_change_cpu", self.change_cpu)
        cfg.set("force_quit_change_mem", self.change_mem)
        cfg.set("force_quit_change_io", self.change_io)
        cfg.set("force_quit_change_alpha", self.change_alpha)
        cfg.set("force_quit_change_ratio", self.change_ratio)
        cfg.set("force_quit_change_std_mult", self.change_std_mult)
        cfg.set("force_quit_change_mad_mult", self.change_mad_mult)
        cfg.set("force_quit_change_decay", self.change_decay)
        cfg.set("force_quit_visible_cpu", self.visible_cpu)
        cfg.set("force_quit_visible_mem", self.visible_mem)
        cfg.set("force_quit_visible_io", self.visible_io)
        cfg.set("force_quit_visible_auto", self.visible_auto)
        cfg.set("force_quit_hide_system", self.hide_system)
        cfg.set("force_quit_exclude_users", sorted(self.exclude_users))
        cfg.set("force_quit_ignore_names", sorted(self.ignore_names))
        cfg.set("force_quit_slow_ratio", self._watcher._slow_ratio)
        cfg.set("force_quit_fast_ratio", self._watcher._fast_ratio)
        cfg.set("force_quit_show_trends", self.show_trends)
        cfg.set("force_quit_show_stable", self.show_stable)
        cfg.set("force_quit_show_deltas", self.show_deltas)
        cfg.set("force_quit_show_normal", self.show_normal)
        cfg.set("force_quit_show_score", self.show_score)
        cfg.set("force_quit_ignore_age", self.ignore_age)
        cfg.set("force_quit_normal_window", self.normal_window)
        cfg.set("force_quit_on_top", bool(self.attributes("-topmost")))
        cfg.set("force_quit_batch_size", self._watcher.batch_size)
        cfg.set("force_quit_auto_batch", self._watcher.auto_batch)
        cfg.set("force_quit_min_batch", self._watcher.min_batch_size)
        cfg.set("force_quit_max_batch", self._watcher.max_batch_size)
        cfg.set("force_quit_min_interval", self._watcher.min_interval)
        cfg.set("force_quit_max_interval", self._watcher.max_interval)
        cfg.set("force_quit_min_workers", self._watcher.min_workers)
        cfg.set("force_quit_max_workers", self._watcher.max_workers)
        cfg.save()
        if self._after_id is not None:
            self.after_cancel(self._after_id)
        self._watcher.stop()
        self._watcher.join(timeout=1.0)
        self._row_cache.clear()
        # Clean up overlay and global mouse hooks
        try:
            self._overlay.close()
        except Exception:
            pass
        try:
            self._listener.stop()
        except Exception:
            pass
        self.destroy()
