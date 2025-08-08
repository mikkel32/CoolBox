import time
from multiprocessing import Queue, Value


def watch_overlay(last_ping: Value, out: Queue, interval: float, misses: int) -> None:
    """Monitor ``last_ping`` and notify ``out`` when it stalls."""
    missed = 0
    while True:
        time.sleep(interval)
        elapsed = time.monotonic() - last_ping.value
        if elapsed <= interval:
            missed = 0
            continue
        missed += 1
        if missed >= misses:
            out.put({"elapsed": elapsed, "misses": missed})
            break
