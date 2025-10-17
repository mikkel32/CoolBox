import sys
import subprocess
import time
import unittest
from unittest import mock
import shutil
import re
import ctypes
from typing import Any, Callable, cast

"""Tests for the force quit dialog interactions.

Like the click overlay suite, these tests monkeypatch Tkinter internals and
platform-specific helpers extensively. Disable general Pyright diagnostics for
the file so behavioural coverage remains the priority.
"""

import os
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import threading

import psutil
import heapq
from queue import Queue

from coolbox.ui.views.dialogs.force_quit import ForceQuitDialog
from coolbox.utils.process_monitor import ProcessEntry, ProcessWatcher


def _make_after_idle_stub() -> tuple[Any, mock.Mock]:
    tracker = mock.Mock()

    def run(func: Callable[..., object], *args: object) -> str:
        tracker(func, *args)
        func(*args)
        return "idle"

    return cast(Any, run), tracker


def _make_after_stub() -> tuple[Any, mock.Mock]:
    tracker = mock.Mock()

    def run(delay: int | str, cb: Callable[..., object], *args: object) -> str:
        tracker(delay, cb, *args)
        cb(*args)
        return "after"

    return cast(Any, run), tracker


class TestForceQuit(unittest.TestCase):
    def test_force_kill(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        pid = proc.pid
        self.assertTrue(psutil.pid_exists(pid))
        ForceQuitDialog.force_kill(pid)
        time.sleep(0.1)
        self.assertFalse(psutil.pid_exists(pid))

    def test_force_kill_ignores_missing_process(self) -> None:
        with mock.patch(
            "coolbox.ui.views.dialogs.force_quit.psutil.pid_exists", return_value=False
        ):
            ok = ForceQuitDialog.force_kill(123456)
        self.assertTrue(ok)

    def test_force_kill_handles_vanished_process(self) -> None:
        with (
            mock.patch(
                "coolbox.ui.views.dialogs.force_quit.psutil.pid_exists",
                side_effect=[True, False],
            ),
            mock.patch(
                "coolbox.ui.views.dialogs.force_quit.kill_process", return_value=False
            ) as kp,
            mock.patch("coolbox.ui.views.dialogs.force_quit.kill_process_tree") as kpt,
        ):
            ok = ForceQuitDialog.force_kill(999)
        self.assertTrue(ok)
        kp.assert_called_once_with(999, timeout=3.0)
        kpt.assert_not_called()

    def test_terminate_tree(self) -> None:
        cmd = [
            sys.executable,
            "-c",
            (
                "import subprocess, sys, time; "
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']);"
                "time.sleep(30)"
            ),
        ]
        proc = subprocess.Popen(cmd)
        children: list[psutil.Process] = []
        for _ in range(10):
            children = psutil.Process(proc.pid).children()
            if children:
                break
            time.sleep(0.1)
        self.assertTrue(children)
        child_pid = children[0].pid
        ForceQuitDialog.terminate_tree(proc.pid)
        time.sleep(0.3)
        self.assertFalse(psutil.pid_exists(proc.pid))
        try:
            child_proc = psutil.Process(child_pid)
        except psutil.NoSuchProcess:
            return
        self.assertIn(
            child_proc.status(),
            {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD},
        )

    def test_force_kill_by_name(self) -> None:
        sleep_bin = shutil.which("sleep")
        if sleep_bin is None:
            self.skipTest("sleep command not available")
        proc = subprocess.Popen([sleep_bin, "30"])
        self.assertTrue(psutil.pid_exists(proc.pid))
        count = ForceQuitDialog.force_kill_by_name("sleep")
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_force_kill_multiple(self) -> None:
        sleep_bin = shutil.which("sleep")
        if sleep_bin is None:
            self.skipTest("sleep command not available")
        p1 = subprocess.Popen([sleep_bin, "30"])
        p2 = subprocess.Popen([sleep_bin, "30"])
        self.assertTrue(psutil.pid_exists(p1.pid))
        self.assertTrue(psutil.pid_exists(p2.pid))
        count = ForceQuitDialog.force_kill_multiple([p1.pid, p2.pid])
        time.sleep(0.1)
        self.assertEqual(count, 2)
        self.assertFalse(psutil.pid_exists(p1.pid))
        self.assertFalse(psutil.pid_exists(p2.pid))

    def test_force_kill_by_pattern(self) -> None:
        sleep_bin = shutil.which("sleep")
        if sleep_bin is None:
            self.skipTest("sleep command not available")
        proc = subprocess.Popen([sleep_bin, "30"])
        self.assertTrue(psutil.pid_exists(proc.pid))
        regex = re.compile("slee?p$", re.IGNORECASE)
        count = ForceQuitDialog.force_kill_by_pattern(regex)
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_force_kill_by_port(self) -> None:
        server = subprocess.Popen([sys.executable, "-m", "http.server", "0"])
        time.sleep(0.2)
        conns = [c for c in psutil.net_connections(kind="inet") if c.pid == server.pid]
        if not conns:
            server.terminate()
            self.skipTest("no connections found")
        conn = cast(Any, conns[0])
        port = int(conn.laddr.port)
        count = ForceQuitDialog.force_kill_by_port(port)
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        self.assertFalse(psutil.pid_exists(server.pid))

    def test_force_kill_by_host(self) -> None:
        server = subprocess.Popen([sys.executable, "-m", "http.server", "0"])
        time.sleep(0.2)
        conns = [c for c in psutil.net_connections(kind="inet") if c.pid == server.pid]
        if not conns:
            server.terminate()
            self.skipTest("no connections found")
        conn = cast(Any, conns[0])
        port = int(conn.laddr.port)
        client = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import socket, time, sys; "
                    f"s=socket.create_connection(('127.0.0.1',{port}));"
                    "time.sleep(30)"
                ),
            ]
        )
        time.sleep(0.2)
        count = ForceQuitDialog.force_kill_by_host("127.0.0.1")
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        self.assertFalse(psutil.pid_exists(client.pid))
        server.terminate()

    def test_force_kill_by_file(self) -> None:
        tmpfile = "/tmp/force_quit_test.txt"
        with open(tmpfile, "w") as f:
            f.write("test")
        proc = subprocess.Popen(
            [sys.executable, "-c", f"open('{tmpfile}','r');import time;time.sleep(30)"]
        )
        time.sleep(0.1)
        self.assertTrue(psutil.pid_exists(proc.pid))
        ForceQuitDialog.force_kill_by_file(tmpfile)
        time.sleep(0.2)
        if psutil.pid_exists(proc.pid):
            ForceQuitDialog.force_kill(proc.pid)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_force_kill_by_executable(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        regex = re.compile(re.escape(sys.executable))
        time.sleep(0.1)
        self.assertTrue(psutil.pid_exists(proc.pid))
        count = ForceQuitDialog.force_kill_by_executable(regex)
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_force_kill_by_executable_excludes_parent(self) -> None:
        regex = re.compile(re.escape(sys.executable))
        parent_pid = os.getppid()
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        time.sleep(0.1)
        self.assertTrue(psutil.pid_exists(proc.pid))
        ForceQuitDialog.force_kill_by_executable(regex)
        time.sleep(0.1)
        self.assertFalse(psutil.pid_exists(proc.pid))
        self.assertTrue(psutil.pid_exists(parent_pid))

    def test_force_kill_by_user(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        user = psutil.Process(proc.pid).username()
        self.assertTrue(psutil.pid_exists(proc.pid))
        regex = re.compile(re.escape(sys.executable))
        count = ForceQuitDialog.force_kill_by_user(user, exe_regex=regex)
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_force_kill_by_cmdline(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        pattern = re.compile(r"time\.sleep")
        self.assertTrue(psutil.pid_exists(proc.pid))
        count = ForceQuitDialog.force_kill_by_cmdline(pattern)
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_force_kill_above_cpu(self) -> None:
        proc = subprocess.Popen(
            [sys.executable, "-c", "while True: pass"], stdout=subprocess.DEVNULL
        )
        time.sleep(0.2)
        self.assertTrue(psutil.pid_exists(proc.pid))
        count = ForceQuitDialog.force_kill_above_cpu(10.0)
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_force_kill_above_memory(self) -> None:
        self.skipTest("memory intensive")
        proc = subprocess.Popen(
            [sys.executable, "-c", "x=' '* (1024*1024); import time; time.sleep(30)"]
        )
        time.sleep(0.2)
        self.assertTrue(psutil.pid_exists(proc.pid))
        count = ForceQuitDialog.force_kill_above_memory(0.5)
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_force_kill_by_parent(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        time.sleep(0.1)
        self.assertTrue(psutil.pid_exists(proc.pid))
        count = ForceQuitDialog.force_kill_by_parent(proc.pid, include_parent=True)
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        try:
            status = psutil.Process(proc.pid).status()
        except psutil.NoSuchProcess:
            status = psutil.STATUS_DEAD
        self.assertIn(status, {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD})

    def test_force_kill_children(self) -> None:
        cmd = [
            sys.executable,
            "-c",
            (
                "import subprocess, sys, time; "
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']);"
                "time.sleep(30)"
            ),
        ]
        proc = subprocess.Popen(cmd)
        time.sleep(0.2)
        child = psutil.Process(proc.pid).children()[0]
        self.assertTrue(psutil.pid_exists(child.pid))
        count = ForceQuitDialog.force_kill_children(proc.pid)
        time.sleep(0.3)
        self.assertGreaterEqual(count, 1)
        try:
            child_status = psutil.Process(child.pid).status()
        except psutil.NoSuchProcess:
            child_status = psutil.STATUS_DEAD
        self.assertIn(child_status, {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD})
        self.assertTrue(psutil.pid_exists(proc.pid))
        ForceQuitDialog.force_kill(proc.pid)

    def test_force_kill_older_than(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        time.sleep(0.1)
        self.assertTrue(psutil.pid_exists(proc.pid))
        regex = re.compile(r"time\.sleep")
        count = ForceQuitDialog.force_kill_older_than(0.0, cmd_regex=regex)
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        try:
            status = psutil.Process(proc.pid).status()
        except psutil.NoSuchProcess:
            status = psutil.STATUS_DEAD
        self.assertIn(status, {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD})

    def test_force_kill_zombies(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import os,time; os._exit(0)"])
        time.sleep(0.1)
        # Wait for zombie state
        start = time.time()
        while time.time() - start < 2.0:
            try:
                if psutil.Process(proc.pid).status() == psutil.STATUS_ZOMBIE:
                    break
            except psutil.NoSuchProcess:
                break
            time.sleep(0.1)
        count = ForceQuitDialog.force_kill_zombies()
        self.assertGreaterEqual(count, 1)

    def test_force_kill_above_threads(self) -> None:
        script = (
            "import threading,time;"
            "[threading.Thread(target=time.sleep,args=(30,)).start() for _ in range(10)];"
            "time.sleep(30)"
        )
        proc = subprocess.Popen([sys.executable, "-c", script])
        time.sleep(0.2)
        self.assertTrue(psutil.pid_exists(proc.pid))
        count = ForceQuitDialog.force_kill_above_threads(5)
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_force_kill_above_io(self) -> None:
        script = (
            "import time,os;"
            "f=open('io_test.tmp','wb');"
            "data=b'0'*1024*1024;"
            "[f.write(data) or f.flush() for _ in range(5)];"
            "time.sleep(30)"
        )
        proc = subprocess.Popen([sys.executable, "-c", script])
        time.sleep(0.2)
        self.assertTrue(psutil.pid_exists(proc.pid))
        ForceQuitDialog.force_kill_above_io(0)
        time.sleep(0.1)
        if psutil.pid_exists(proc.pid):
            ForceQuitDialog.force_kill(proc.pid)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_force_kill_above_files(self) -> None:
        script = (
            "import tempfile,time;"
            "files=[open(tempfile.mkstemp()[1],'wb') for _ in range(6)];"
            "time.sleep(30)"
        )
        proc = subprocess.Popen([sys.executable, "-c", script])
        time.sleep(0.2)
        self.assertTrue(psutil.pid_exists(proc.pid))
        count = ForceQuitDialog.force_kill_above_files(4)
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_force_kill_above_conns(self) -> None:
        script = (
            "import socket,threading,time;"
            "srv=socket.socket();"
            "srv.bind(('127.0.0.1',0));srv.listen();"
            "port=srv.getsockname()[1];"
            "threading.Thread(target=lambda: [srv.accept() for _ in range(6)], daemon=True).start();"
            "s=[socket.create_connection(('127.0.0.1',port)) for _ in range(6)];"
            "time.sleep(30)"
        )
        proc = subprocess.Popen([sys.executable, "-c", script])
        time.sleep(0.5)
        self.assertTrue(psutil.pid_exists(proc.pid))
        count = ForceQuitDialog.force_kill_above_conns(4)
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_force_kill_sustained_cpu(self) -> None:
        proc = subprocess.Popen(
            [sys.executable, "-c", "while True: pass"], stdout=subprocess.DEVNULL
        )
        time.sleep(0.2)
        self.assertTrue(psutil.pid_exists(proc.pid))
        count = ForceQuitDialog.force_kill_sustained_cpu(10.0, duration=0.5)
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_find_over_threshold(self) -> None:
        e1 = ProcessEntry(
            pid=1,
            name="p1",
            cpu=90.0,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        e2 = ProcessEntry(
            pid=2,
            name="p2",
            cpu=10.0,
            mem=600.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        snapshot = {1: e1, 2: e2}
        pids = ForceQuitDialog._find_over_threshold(
            snapshot,
            kill_cpu=True,
            kill_mem=True,
            cpu_alert=80.0,
            mem_alert=500.0,
        )
        assert set(pids) == {1, 2}

    def test_heap_ordering_no_error(self) -> None:
        """Ensure heap operations don't compare ProcessEntry instances."""
        e1 = ProcessEntry(
            pid=1,
            name="p1",
            cpu=50.0,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        e2 = ProcessEntry(
            pid=2,
            name="p2",
            cpu=50.0,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        heap: list[tuple[tuple[float, float, int], ProcessEntry]] = []
        heapq.heappush(heap, ((e1.avg_cpu, e1.mem, e1.pid), e1))
        heapq.heappush(heap, ((e2.avg_cpu, e2.mem, e2.pid), e2))
        ordered = [e.pid for _s, e in heapq.nlargest(2, heap)]
        assert set(ordered) == {1, 2}

    def test_change_thresholds(self) -> None:
        ProcessEntry.change_ratio = 0.0
        ProcessEntry.change_score_threshold = 5.0
        base = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.0,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        small = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.3,
            mem=100.2,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        large = ProcessEntry(
            pid=1,
            name="p",
            cpu=12.0,
            mem=102.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        score_small = small._change_score(base)
        assert score_small < ProcessEntry.change_score_threshold
        assert not small.changed_since(base)
        score_large = large._change_score(base)
        assert score_large >= ProcessEntry.change_score_threshold

    def test_change_score_threshold(self) -> None:
        ProcessEntry.change_score_threshold = 2.0
        ProcessEntry.change_mad_mult = 100.0
        base = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.0,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        other = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.1,
            mem=100.1,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        assert not other.changed_basic(base)
        ProcessEntry.change_score_threshold = 3.0
        ProcessEntry.change_mad_mult = 3.0

    def test_change_delta_thresholds(self) -> None:
        ProcessEntry.cpu_threshold = 1.0
        ProcessEntry.mem_threshold = 2.0
        ProcessEntry.io_threshold = 2.0
        ProcessEntry.change_std_mult = 2.0
        ProcessEntry.change_score_threshold = 100.0
        base = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.0,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        other = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.5,
            mem=101.5,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
            io_rate=3.0,
        )
        assert not other.changed_basic(base)
        base = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.0,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        ProcessEntry.cpu_threshold = 0.3
        ProcessEntry.change_score_threshold = 3.0
        other = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.5,
            mem=101.5,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
            io_rate=3.0,
        )
        assert other.changed_basic(base)
        ProcessEntry.cpu_threshold = 0.5
        ProcessEntry.mem_threshold = 1.0
        ProcessEntry.io_threshold = 0.5
        ProcessEntry.change_score_threshold = 3.0

    def test_change_agg_window(self) -> None:
        ProcessEntry.change_score_threshold = 1.5
        ProcessEntry.change_agg_window = 3
        ProcessEntry.change_ratio = 0.0
        base = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.0,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        step1 = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.2,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        assert not base.changed_basic(step1)
        base.cpu = step1.cpu
        step2 = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.4,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        assert not base.changed_basic(step2)
        base.cpu = step2.cpu
        step3 = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.6,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        assert base.changed_basic(step3)
        ProcessEntry.change_agg_window = 1

    def test_change_std_mult(self) -> None:
        ProcessEntry.change_std_mult = 3.0
        ProcessEntry.change_ratio = 0.0
        ProcessEntry.cpu_threshold = 0.2
        ProcessEntry.mem_threshold = 0.2
        ProcessEntry.change_score_threshold = 3.0
        base = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.0,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        small = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.1,
            mem=100.1,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        assert not base.changed_basic(small)
        for _ in range(5):
            base.changed_basic(base)
        large = ProcessEntry(
            pid=1,
            name="p",
            cpu=12.0,
            mem=105.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        assert base.changed_basic(large)
        ProcessEntry.change_std_mult = 2.0

    def test_change_mad_mult(self) -> None:
        ProcessEntry.change_mad_mult = 4.0
        ProcessEntry.change_ratio = 0.0
        ProcessEntry.cpu_threshold = 0.2
        ProcessEntry.mem_threshold = 0.2
        ProcessEntry.change_score_threshold = 3.0
        base = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.0,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        slight = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.2,
            mem=100.2,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        assert not base.changed_basic(slight)
        for _ in range(5):
            base.changed_basic(slight)
        spike = ProcessEntry(
            pid=1,
            name="p",
            cpu=13.0,
            mem=110.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        assert base.changed_basic(spike)
        ProcessEntry.change_mad_mult = 3.0

    def test_stable_env_vars(self) -> None:
        q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
        watcher = ProcessWatcher(q, stable_cycles=5, stable_skip=2)
        assert watcher._stable_cycles == 5
        assert watcher._stable_skip == 2
        watcher.stop()

    def test_hide_system(self) -> None:
        q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
        watcher = ProcessWatcher(q, hide_system=True)
        assert watcher.hide_system is True
        watcher.stop()

    def test_exclude_users(self) -> None:
        q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
        watcher = ProcessWatcher(q, exclude_users={"root", "daemon"})
        assert watcher.exclude_users == {"root", "daemon"}
        watcher.stop()

    def test_process_entry_delta_fields(self) -> None:
        entry = ProcessEntry(
            pid=1,
            name="p",
            cpu=1.0,
            mem=10.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        assert hasattr(entry, "delta_cpu")
        assert hasattr(entry, "delta_mem")
        assert hasattr(entry, "delta_io")
        assert entry.changed is False

    def test_process_entry_last_score(self) -> None:
        base = ProcessEntry(
            pid=1,
            name="p",
            cpu=1.0,
            mem=10.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        other = ProcessEntry(
            pid=1,
            name="p",
            cpu=2.0,
            mem=12.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        base.changed_basic(other)
        assert base.last_score > 0

    def test_process_entry_stable_flag(self) -> None:
        entry = ProcessEntry(
            pid=1,
            name="p",
            cpu=0.0,
            mem=1.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        assert entry.stable is False
        entry.stable = True
        assert entry.stable

    def test_ratio_env_vars(self) -> None:
        q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
        watcher = ProcessWatcher(q, slow_ratio=0.05, fast_ratio=0.3)
        assert watcher._slow_ratio == 0.05
        assert watcher._fast_ratio == 0.3
        watcher.stop()

    def test_ratio_window_option(self) -> None:
        q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
        watcher = ProcessWatcher(q, ratio_window=7)
        assert watcher._ratio_window == 7
        watcher.stop()

    def test_normal_window_option(self) -> None:
        q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
        watcher = ProcessWatcher(q, normal_window=4)
        assert watcher._normal_window == 4
        watcher.stop()

    def test_visible_auto_option(self) -> None:
        q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
        watcher = ProcessWatcher(q, visible_auto=True)
        assert watcher.visible_auto is True
        watcher.stop()

    def test_auto_baselines(self) -> None:
        q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
        watcher = ProcessWatcher(q, visible_auto=True)
        watcher._update_auto_baselines(
            [1.0, 2.0, 3.0, 4.0], [10, 20, 30, 40], [0.1, 0.2, 0.3, 0.4]
        )
        assert round(watcher._auto_cpu, 1) == 3.0
        assert round(watcher._auto_mem, 1) == 30.0
        assert round(watcher._auto_io, 1) == 0.3
        watcher.stop()

    def test_trend_env_vars(self) -> None:
        q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
        watcher = ProcessWatcher(
            q, trend_window=6, trend_cpu=2.5, trend_mem=20.0, trend_io=0.5
        )
        assert watcher._trend_window == 6
        assert watcher._trend_cpu == 2.5
        assert watcher._trend_mem == 20.0
        assert watcher._trend_io == 0.5
        watcher.stop()

    def test_trend_io_window(self) -> None:
        q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
        watcher = ProcessWatcher(q, trend_io_window=7)
        assert watcher._trend_io_window == 7
        watcher.stop()

    def test_trend_ratio_env_vars(self) -> None:
        q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
        watcher = ProcessWatcher(q, trend_slow_ratio=0.1, trend_fast_ratio=0.4)
        assert watcher._trend_slow_ratio == 0.1
        assert watcher._trend_fast_ratio == 0.4
        watcher.stop()

    def test_ignore_age_option(self) -> None:
        q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
        watcher = ProcessWatcher(q, ignore_age=2.5)
        assert watcher.ignore_age == 2.5
        watcher.stop()

    def test_change_mad_option(self) -> None:
        q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
        watcher = ProcessWatcher(q, change_mad_mult=5.0)
        assert watcher.change_mad_mult == 5.0
        watcher.stop()

    def test_change_decay(self) -> None:
        ProcessEntry.change_score_threshold = 3.0
        ProcessEntry.cpu_threshold = 0.1
        ProcessEntry.change_decay = 0.5
        ProcessEntry.change_ratio = 0.0
        ProcessEntry.change_alpha = 0.0
        base = ProcessEntry(
            pid=1,
            name="p",
            cpu=1.0,
            mem=1.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        other = ProcessEntry(
            pid=1,
            name="p",
            cpu=1.2,
            mem=1.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        assert not base.changed_basic(other)
        assert not base.changed_basic(other)
        assert base.changed_basic(other)

    def test_compute_trends(self) -> None:
        entry = ProcessEntry(
            pid=1,
            name="p",
            cpu=5.0,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
            max_samples=20,
        )
        for i in range(10):
            entry.add_sample(5.0 + i, 0.2 * i, 100.0 + i)
        entry.compute_trends(5, 5, 5, 1.0, 4.0, 0.5)
        assert entry.trending_cpu
        assert entry.trending_mem
        assert entry.trending_io

    def test_update_level(self) -> None:
        entry = ProcessEntry(
            pid=1,
            name="p",
            cpu=45.0,
            mem=300.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        entry.update_level(40.0, 200.0, 1.0, 80.0, 500.0)
        assert entry.level == "warning"
        entry.cpu = 90.0
        entry.update_level(40.0, 200.0, 1.0, 80.0, 500.0)
        assert entry.level == "critical"

    def test_baseline_change_detection(self) -> None:
        ProcessEntry.change_alpha = 0.5
        ProcessEntry.change_ratio = 0.3
        base = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.0,
            mem=100.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        small = ProcessEntry(
            pid=1,
            name="p",
            cpu=10.2,
            mem=100.1,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        assert not base.changed_basic(small)
        large = ProcessEntry(
            pid=1,
            name="p",
            cpu=14.0,
            mem=115.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        assert base.changed_basic(large)

    def test_baseline_variance(self) -> None:
        ProcessEntry.change_alpha = 0.5
        ProcessEntry.change_std_mult = 2.0
        base = ProcessEntry(
            pid=1,
            name="p",
            cpu=5.0,
            mem=50.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        for i in range(10):
            sample = ProcessEntry(
                pid=1,
                name="p",
                cpu=5.0 + i * 0.1,
                mem=50.0,
                user="u",
                start=0.0,
                status="",
                cpu_time=0.0,
                threads=1,
                read_bytes=0,
                write_bytes=0,
                files=0,
                conns=0,
            )
            base.changed_basic(sample)
        assert base.baseline_cpu_var > 0
        assert base.baseline_cpu_mad > 0
        spike = ProcessEntry(
            pid=1,
            name="p",
            cpu=8.0,
            mem=50.0,
            user="u",
            start=0.0,
            status="",
            cpu_time=0.0,
            threads=1,
            read_bytes=0,
            write_bytes=0,
            files=0,
            conns=0,
        )
        assert base.changed_basic(spike)

    def test_force_kill_active_window(self) -> None:
        if ForceQuitDialog._get_active_window_pid() is None:
            self.skipTest("active window detection unavailable")
        script = (
            "import tkinter as tk, time;"
            "root=tk.Tk();root.title('FKAW');"
            "root.after(60000, lambda: None);root.mainloop()"
        )
        proc = subprocess.Popen([sys.executable, "-c", script])
        time.sleep(1.0)
        if sys.platform.startswith("linux"):
            xdotool = shutil.which("xdotool")
            if xdotool:
                subprocess.run(
                    [xdotool, "search", "--name", "FKAW", "windowactivate"], check=False
                )
                time.sleep(0.5)
        elif sys.platform.startswith("win"):
            try:
                hwnd = cast(Any, ctypes).windll.user32.FindWindowW(None, "FKAW")
                if hwnd:
                    cast(Any, ctypes).windll.user32.SetForegroundWindow(hwnd)
                    time.sleep(0.5)
            except Exception:
                pass
        elif sys.platform == "darwin":
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to set frontmost of (first process whose name is "Python") to true',
                ],
                check=False,
            )
            time.sleep(0.5)
        focused = False
        for _ in range(10):
            pid = ForceQuitDialog._get_active_window_pid()
            if pid == proc.pid:
                focused = True
                break
            time.sleep(0.2)
        if not focused:
            proc.terminate()
            self.skipTest("could not focus window")
        ForceQuitDialog.force_kill_active_window()
        time.sleep(0.2)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_force_kill_window_under_cursor(self) -> None:
        if ForceQuitDialog._get_window_under_cursor().pid is None:
            self.skipTest("cursor window detection unavailable")
        script = (
            "import tkinter as tk, time;"
            "root=tk.Tk();root.title('FKWC');"
            "root.after(60000, lambda: None);root.update();"
            "print(root.winfo_rootx(), root.winfo_rooty(), flush=True);"
            "root.mainloop()"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", script], stdout=subprocess.PIPE, text=True
        )
        assert proc.stdout is not None
        coords = proc.stdout.readline()
        x, y = (int(v) + 10 for v in coords.split())
        if sys.platform.startswith("win"):
            cast(Any, ctypes).windll.user32.SetCursorPos(x, y)
        elif sys.platform.startswith("linux"):
            xdotool = shutil.which("xdotool")
            if xdotool:
                subprocess.run([xdotool, "mousemove", str(x), str(y)], check=False)
        time.sleep(0.5)
        ForceQuitDialog.force_kill_window_under_cursor()
        time.sleep(0.2)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_kill_by_click_pauses_watcher(self) -> None:
        dialog = ForceQuitDialog.__new__(ForceQuitDialog)
        dialog._overlay_thread = None
        dialog.accent = "#f00"
        dialog.paused = False
        dialog._watcher = mock.Mock()
        dialog._populate = mock.Mock()
        dialog.withdraw = mock.Mock()
        dialog.deiconify = mock.Mock()
        dialog.after_idle, after_idle_tracker = _make_after_idle_stub()
        overlay = mock.Mock()
        overlay.choose.return_value = (None, None)
        overlay.canvas = mock.Mock()
        overlay.rect = object()
        overlay.hline = object()
        overlay.vline = object()
        overlay.label = object()
        overlay.reset = mock.Mock()
        overlay.apply_defaults = mock.Mock()
        dialog._overlay = overlay
        dialog.app = SimpleNamespace(config={})
        dialog._configure_overlay()
        overlay.apply_defaults.assert_called_once()

        dialog.after, after_tracker = _make_after_stub()
        with mock.patch("coolbox.ui.views.dialogs.force_quit.messagebox") as MB:
            dialog._kill_by_click()
            if dialog._overlay_thread:
                dialog._overlay_thread.join(timeout=1)
            dialog._watcher.pause.assert_called_once()
            dialog._watcher.resume.assert_called_once()
            MB.showerror.assert_not_called()
            after_idle_tracker.assert_called_with(dialog._update_hover)
            overlay.choose.assert_called_once()
            overlay.reset.assert_called_once()
            overlay.apply_defaults.assert_called_once()
        assert after_tracker.call_args_list[0].args[0] == 0

    def test_kill_by_click_exception_cleanup(self) -> None:
        dialog = ForceQuitDialog.__new__(ForceQuitDialog)
        dialog._overlay_thread = None
        dialog._overlay_thread = None
        dialog.accent = "#f00"
        dialog.paused = False
        dialog._watcher = mock.Mock()
        dialog._populate = mock.Mock()
        dialog.withdraw = mock.Mock()
        dialog.deiconify = mock.Mock()
        dialog.after_idle, after_idle_tracker = _make_after_idle_stub()
        dialog._update_hover = mock.Mock()
        dialog._highlight_pid = mock.Mock()
        dialog._highlight_pid = mock.Mock()
        overlay = mock.Mock()
        overlay.choose.side_effect = RuntimeError("boom")
        overlay.reset = mock.Mock()
        overlay.set_highlight_color = mock.Mock()
        overlay.interval = None
        overlay.min_interval = None
        overlay.max_interval = None
        overlay.delay_scale = None
        overlay.apply_defaults = mock.Mock()
        dialog._overlay = overlay
        dialog.app = SimpleNamespace(config={})
        dialog._configure_overlay()
        overlay.apply_defaults.assert_called_once()

        dialog.after, after_tracker = _make_after_stub()
        hook = threading.excepthook
        threading.excepthook = lambda args: None
        try:
            with mock.patch("coolbox.ui.views.dialogs.force_quit.messagebox"):
                dialog._kill_by_click()
                if dialog._overlay_thread:
                    dialog._overlay_thread.join(timeout=1)
        finally:
            threading.excepthook = hook
        dialog.withdraw.assert_called_once()
        dialog.deiconify.assert_called_once()
        dialog._watcher.pause.assert_called_once()
        dialog._watcher.resume.assert_called_once()
        overlay.reset.assert_called_once()
        dialog._highlight_pid.assert_called_with(None, None)
        after_idle_tracker.assert_called_with(dialog._update_hover)
        overlay.apply_defaults.assert_called_once()
        assert after_tracker.call_args_list[0].args[0] == 0

    def test_kill_by_click_skip_confirm(self) -> None:
        dialog = ForceQuitDialog.__new__(ForceQuitDialog)
        dialog._overlay_thread = None
        dialog._overlay_thread = None
        dialog.accent = "#f00"
        dialog.paused = True
        dialog._watcher = mock.Mock()
        dialog._populate = mock.Mock()
        dialog.withdraw = mock.Mock()
        dialog.deiconify = mock.Mock()
        dialog.force_kill = mock.Mock(return_value=True)
        dialog.after_idle, after_idle_tracker = _make_after_idle_stub()
        overlay = mock.Mock()
        overlay.choose.return_value = (123, "foo")
        overlay.canvas = mock.Mock()
        overlay.rect = object()
        overlay.hline = object()
        overlay.vline = object()
        overlay.label = object()
        overlay.reset = mock.Mock()
        overlay.apply_defaults = mock.Mock()
        dialog._overlay = overlay
        dialog.app = SimpleNamespace(config={})

        dialog.after, after_tracker = _make_after_stub()
        with (
            mock.patch.dict(os.environ, {"FORCE_QUIT_CLICK_SKIP_CONFIRM": "1"}),
            mock.patch("coolbox.ui.views.dialogs.force_quit.messagebox") as MB,
        ):
            dialog._configure_overlay()
            dialog._kill_by_click()
            if dialog._overlay_thread:
                dialog._overlay_thread.join(timeout=1)
            MB.askyesno.assert_not_called()
            MB.showinfo.assert_called_once()
            dialog.force_kill.assert_called_once_with(123)
        overlay.apply_defaults.assert_called_once()
        assert after_tracker.call_args_list[0].args[0] == 0

    def test_kill_by_click_per_run_isolation(self) -> None:
        dialog = ForceQuitDialog.__new__(ForceQuitDialog)
        dialog._overlay_thread = None
        dialog._overlay_thread = None
        dialog.accent = "#f00"
        dialog.paused = False
        dialog._watcher = mock.Mock()
        dialog._populate = mock.Mock()
        dialog.withdraw = mock.Mock()
        dialog.deiconify = mock.Mock()
        dialog.after_idle, after_idle_tracker = _make_after_idle_stub()
        dialog._update_hover = mock.Mock()
        overlay = mock.Mock()
        overlay.canvas = mock.Mock()
        overlay.rect = object()
        overlay.hline = object()
        overlay.vline = object()
        overlay.label = object()
        default_interval = 0.3

        def apply_defaults() -> None:
            overlay.interval = default_interval

        def choose_side_effect() -> tuple[None, None]:
            overlay.interval = 0.1
            return (None, None)

        def reset_side_effect() -> None:
            overlay.interval = default_interval

        overlay.apply_defaults.side_effect = apply_defaults
        overlay.choose.side_effect = choose_side_effect
        overlay.reset.side_effect = reset_side_effect
        dialog._overlay = overlay
        dialog.app = SimpleNamespace(config={})
        dialog._configure_overlay()
        self.assertEqual(overlay.apply_defaults.call_count, 1)
        dialog.after, after_tracker = _make_after_stub()
        with mock.patch("coolbox.ui.views.dialogs.force_quit.messagebox"):
            dialog._kill_by_click()
            if dialog._overlay_thread:
                dialog._overlay_thread.join(timeout=1)
            self.assertEqual(overlay.interval, default_interval)
            assert after_tracker.call_args_list[0].args[0] == 0
            after_tracker.reset_mock()
            overlay.interval = 0.5
            dialog._kill_by_click()
            if dialog._overlay_thread:
                dialog._overlay_thread.join(timeout=1)
            self.assertEqual(overlay.interval, default_interval)
            assert after_tracker.call_args_list[0].args[0] == 0

        self.assertEqual(overlay.apply_defaults.call_count, 1)
        self.assertEqual(overlay.reset.call_count, 2)

    def test_kill_by_click_nonblocking_and_cancel(self) -> None:
        dialog = ForceQuitDialog.__new__(ForceQuitDialog)
        dialog._overlay_thread = None
        dialog._overlay_thread = None
        dialog.accent = "#f00"
        dialog.paused = False
        dialog._watcher = mock.Mock()
        dialog._populate = mock.Mock()
        dialog.force_kill = mock.Mock(return_value=True)
        dialog.withdraw = mock.Mock()
        dialog.deiconify = mock.Mock()
        dialog.after_idle, after_idle_tracker = _make_after_idle_stub()
        dialog._update_hover = mock.Mock()
        overlay = mock.Mock()
        overlay.canvas = mock.Mock()
        overlay.rect = object()
        overlay.hline = object()
        overlay.vline = object()
        overlay.label = object()
        overlay.reset = mock.Mock()
        overlay.apply_defaults = mock.Mock()
        blocker = threading.Event()
        cancelled = {"flag": False}

        def choose() -> tuple[int | None, str | None]:
            blocker.wait()
            if cancelled["flag"]:
                return (None, None)
            return (456, "foo")

        overlay.choose.side_effect = choose

        def close_side_effect() -> None:
            cancelled["flag"] = True
            blocker.set()

        overlay.close.side_effect = close_side_effect
        dialog._overlay = overlay
        dialog.app = SimpleNamespace(config={})
        dialog.after, after_tracker = _make_after_stub()
        dialog._configure_overlay()
        start = time.time()
        with mock.patch("coolbox.ui.views.dialogs.force_quit.messagebox"):
            dialog._kill_by_click()
        elapsed = time.time() - start
        self.assertLess(elapsed, 0.1)
        assert after_tracker.call_args_list[0].args[0] == 0
        dialog.cancel_kill_by_click()
        overlay.close.assert_called_once()
        blocker.set()
        if dialog._overlay_thread:
            dialog._overlay_thread.join(timeout=1)
        dialog.force_kill.assert_not_called()

    def test_configure_overlay_applies_updates(self) -> None:
        dialog = ForceQuitDialog.__new__(ForceQuitDialog)
        dialog._overlay_thread = None
        dialog._overlay_thread = None
        dialog.accent = "#f00"
        dialog._highlight_pid = mock.Mock()
        overlay = mock.Mock()
        overlay.apply_defaults = mock.Mock()
        overlay.skip_confirm = False
        dialog._overlay = overlay
        dialog.app = SimpleNamespace(config={})

        with mock.patch.dict(
            os.environ,
            {"FORCE_QUIT_CLICK_SKIP_CONFIRM": "0", "KILL_BY_CLICK_HIGHLIGHT": "blue"},
        ):
            dialog._configure_overlay()
            self.assertFalse(overlay.skip_confirm)
            self.assertEqual(overlay.set_highlight_color.call_args_list[-1][0][0], "blue")

        with mock.patch.dict(
            os.environ,
            {"FORCE_QUIT_CLICK_SKIP_CONFIRM": "1", "KILL_BY_CLICK_HIGHLIGHT": "green"},
        ):
            dialog._configure_overlay()
            self.assertTrue(overlay.skip_confirm)
            self.assertEqual(overlay.set_highlight_color.call_args_list[-1][0][0], "green")

        self.assertEqual(overlay.apply_defaults.call_count, 2)

    def test_highlight_pid_skips_duplicate_selection(self) -> None:
        dialog = ForceQuitDialog.__new__(ForceQuitDialog)
        tree = mock.Mock()
        tree.exists.return_value = True
        tree.selection.return_value = ("123",)
        dialog.tree = tree
        dialog._set_hover_row = mock.Mock()
        dialog._show_details = mock.Mock()

        dialog._highlight_pid(123)

        tree.selection_set.assert_not_called()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_hover_highlights_row(self) -> None:
        root = tk.Tk()
        tree = ttk.Treeview(root)
        tree.insert("", "end", iid="1", values=("foo",))
        dialog = ForceQuitDialog.__new__(ForceQuitDialog)
        dialog.tree = tree
        dialog._hover_iid = None
        dialog.hover_color = "#eee"
        tree.tag_configure("hover", background=dialog.hover_color)
        bbox = cast(tuple[int, int, int, int], tree.bbox("1"))
        event = tk.Event()
        event.y = bbox[1] + 1
        dialog._on_hover(event)
        self.assertIn("hover", tree.item("1", "tags"))
        dialog._set_hover_row(None)
        self.assertNotIn("hover", tree.item("1", "tags"))
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_update_hover_picks_row(self) -> None:
        root = tk.Tk()
        tree = ttk.Treeview(root)
        tree.insert("", "end", iid="1", values=("foo",))
        dialog = ForceQuitDialog.__new__(ForceQuitDialog)
        dialog.tree = tree
        dialog._hover_iid = None
        dialog.hover_color = "#eee"
        tree.tag_configure("hover", background=dialog.hover_color)
        bbox = cast(tuple[int, int, int, int], tree.bbox("1"))
        root.update_idletasks()
        dialog.winfo_pointerxy = lambda: (
            tree.winfo_rootx() + bbox[0] + 2,
            tree.winfo_rooty() + bbox[1] + 2,
        )
        dialog.winfo_containing = root.winfo_containing
        dialog._update_hover()
        self.assertIn("hover", tree.item("1", "tags"))
        root.destroy()

    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_set_hover_row_handles_missing(self) -> None:
        root = tk.Tk()
        tree = ttk.Treeview(root)
        tree.insert("", "end", iid="1", values=("foo",))
        dialog = ForceQuitDialog.__new__(ForceQuitDialog)
        dialog.tree = tree
        dialog._hover_iid = None
        dialog.hover_color = "#eee"
        tree.tag_configure("hover", background=dialog.hover_color)
        dialog._set_hover_row("1")
        self.assertIn("hover", tree.item("1", "tags"))
        tree.delete("1")
        dialog._set_hover_row("1")
        self.assertIsNone(dialog._hover_iid)
        root.destroy()


if __name__ == "__main__":
    unittest.main()
