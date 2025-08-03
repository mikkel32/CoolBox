"""NumPy-accelerated weighted confidence scoring.

This module provides a drop-in replacement for the Python implementation
of :meth:`ScoringEngine.weighted_confidence`. When NumPy is available the
probability calculations are performed with vectorized operations; if it
is not installed we fall back to the original method so callers do not
need to handle ImportError.
"""

from __future__ import annotations

from typing import Deque, Tuple, List

try:  # Optional NumPy acceleration
    import numpy as _np
except Exception:  # pragma: no cover - optional dependency
    _np = None

from src.utils.scoring_engine import ScoringEngine
from src.utils.window_utils import WindowInfo


def weighted_confidence(
    engine: ScoringEngine,
    samples: List[WindowInfo],
    cursor_x: float,
    cursor_y: float,
    velocity: float,
    path_history: Deque[Tuple[int, int]],
    initial_active_pid: int | None,
) -> Tuple[WindowInfo | None, float, float]:
    """Return ``(info, ratio, probability)`` for ``samples``.

    The heavy probability math is executed with NumPy when available to
    avoid Python-level loops. When NumPy is not installed the function
    simply delegates to ``engine.weighted_confidence``.
    """

    if _np is None:
        return engine.weighted_confidence(
            samples, cursor_x, cursor_y, velocity, path_history, initial_active_pid
        )

    weights = engine.score_samples(
        samples, cursor_x, cursor_y, velocity, path_history, initial_active_pid
    )
    if not weights:
        return None, 0.0, 0.0

    w_arr = _np.fromiter(weights.values(), dtype=_np.float64)
    scale = 1.0 / max(engine.tuning.softmax_temp, 1e-6)
    exps = _np.exp(w_arr * scale)
    probs = exps / _np.sum(exps)
    best_idx = int(_np.argmax(probs))
    best_prob = float(probs[best_idx])
    if probs.size > 1:
        second_prob = float(_np.partition(probs, -2)[-2])
    else:
        second_prob = 0.0
    ratio = best_prob / (second_prob or 1e-6)
    info = engine.select_from_weights(samples, weights)
    return info, ratio, best_prob
