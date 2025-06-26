import sys
import subprocess
import time
import unittest
import shutil
import re

import psutil

from src.views.force_quit_dialog import ForceQuitDialog, ProcessEntry


class TestForceQuit(unittest.TestCase):
    def test_force_kill(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        pid = proc.pid
        self.assertTrue(psutil.pid_exists(pid))
        ForceQuitDialog.force_kill(pid)
        time.sleep(0.1)
        self.assertFalse(psutil.pid_exists(pid))

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
        time.sleep(0.1)
        children = psutil.Process(proc.pid).children()
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
        port = conns[0].laddr.port
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
        port = conns[0].laddr.port
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
        proc = subprocess.Popen([sys.executable, "-c", f"open('{tmpfile}','r');import time;time.sleep(30)"])
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
        proc = subprocess.Popen([sys.executable, "-c", "while True: pass"], stdout=subprocess.DEVNULL)
        time.sleep(0.2)
        self.assertTrue(psutil.pid_exists(proc.pid))
        count = ForceQuitDialog.force_kill_above_cpu(10.0)
        time.sleep(0.1)
        self.assertGreaterEqual(count, 1)
        self.assertFalse(psutil.pid_exists(proc.pid))

    def test_force_kill_above_memory(self) -> None:
        self.skipTest("memory intensive")
        proc = subprocess.Popen([sys.executable, "-c", "x=' '* (1024*1024); import time; time.sleep(30)"])
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
        proc = subprocess.Popen([sys.executable, "-c", "while True: pass"], stdout=subprocess.DEVNULL)
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


if __name__ == "__main__":
    unittest.main()
