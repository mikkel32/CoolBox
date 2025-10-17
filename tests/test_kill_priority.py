import sys
import subprocess
import time
from contextlib import contextmanager
from unittest import mock

import psutil

from coolbox.utils.kill_utils import kill_process


def test_kill_process_uses_priority_boost():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    assert psutil.pid_exists(proc.pid)
    called = False

    @contextmanager
    def fake_boost():
        nonlocal called
        called = True
        yield

    with mock.patch("coolbox.utils.kill_utils._priority_boost", fake_boost):
        kill_process(proc.pid, timeout=1.0)

    time.sleep(0.1)
    assert called
    assert not psutil.pid_exists(proc.pid)
