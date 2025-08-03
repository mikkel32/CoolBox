import subprocess
import sys
import time

from src.utils import ProcessCache


def test_process_cache_updates_on_invalidate():
    cache = ProcessCache()
    cache.snapshot()
    # Spawn a short-lived subprocess
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.1)"])
    try:
        cache.invalidate()  # simulate notification
        snap = cache.snapshot()
        assert proc.pid in snap
    finally:
        proc.wait()
    cache.invalidate()
    time.sleep(0.01)
    snap2 = cache.snapshot()
    assert proc.pid not in snap2
