import sys
import subprocess
import time
import unittest
import os

import psutil

from src.utils.kill_utils import kill_process, kill_process_tree


class TestKillUtils(unittest.TestCase):
    def test_kill_process(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        pid = proc.pid
        self.assertTrue(psutil.pid_exists(pid))
        kill_process(pid)
        time.sleep(0.1)
        self.assertFalse(psutil.pid_exists(pid))

    def test_kill_process_tree(self) -> None:
        cmd = [
            sys.executable,
            "-c",
            (
                "import subprocess, time, sys;"
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']);"
                "time.sleep(30)"
            ),
        ]
        parent = subprocess.Popen(cmd)
        time.sleep(0.2)
        children = psutil.Process(parent.pid).children()
        self.assertTrue(children)
        kill_process_tree(parent.pid)
        time.sleep(0.2)
        self.assertFalse(psutil.pid_exists(parent.pid))
        for c in children:
            try:
                status = psutil.Process(c.pid).status()
            except psutil.NoSuchProcess:
                status = psutil.STATUS_DEAD
            self.assertIn(status, {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD})

    @unittest.skipIf(os.name == "nt", "process groups not supported")
    def test_kill_process_group(self) -> None:
        cmd = [
            sys.executable,
            "-c",
            (
                "import os, subprocess, sys, time;"
                "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']);"
                "time.sleep(30)"
            ),
        ]
        proc = subprocess.Popen(cmd, preexec_fn=os.setsid)
        time.sleep(0.2)
        children = psutil.Process(proc.pid).children()
        self.assertTrue(children)
        child_pid = children[0].pid
        kill_process_tree(proc.pid)
        time.sleep(0.2)
        self.assertFalse(psutil.pid_exists(proc.pid))
        if psutil.pid_exists(child_pid):
            status = psutil.Process(child_pid).status()
            self.assertIn(status, {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD})


if __name__ == "__main__":
    unittest.main()
