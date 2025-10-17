from __future__ import annotations

"""GPU benchmarking helpers."""

import time
from typing import List


def benchmark_gpu_usage(samples: int = 5, interval: float = 0.1) -> List[float]:
    """Return GPU load percentages sampled over time.

    Uses :mod:`GPUtil` when available. Returns an empty list when no GPUs are
    detected or the library is missing.
    """
    try:
        import GPUtil  # type: ignore

        gpus = GPUtil.getGPUs()
    except Exception:
        return []
    if not gpus:
        return []
    usages: List[float] = []
    for _ in range(samples):
        for gpu in gpus:
            try:
                usages.append(gpu.load * 100)
            except Exception:
                usages.append(0.0)
        time.sleep(interval)
    return usages
