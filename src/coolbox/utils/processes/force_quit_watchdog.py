import json
import os
import sys
import time
from pathlib import Path


def main(path: str, interval: float, misses: int) -> None:
    """Monitor ``path`` for ping updates and report when stalled."""
    missed = 0
    ping_path = Path(path)
    while True:
        time.sleep(interval)
        try:
            last = ping_path.stat().st_mtime
        except FileNotFoundError:
            break
        except OSError:
            continue
        elapsed = time.time() - last
        if elapsed <= interval:
            missed = 0
            continue
        missed += 1
        if missed >= misses:
            json.dump({"elapsed": elapsed, "misses": missed}, sys.stdout)
            sys.stdout.write("\n")
            sys.stdout.flush()
            break


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    main(sys.argv[1], float(sys.argv[2]), int(sys.argv[3]))

