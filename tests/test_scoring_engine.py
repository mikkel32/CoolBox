import math
import time
from collections import deque

import pytest

from src.utils.scoring_engine import ScoringEngine, Tuning


def test_gaze_weight_recency_decay() -> None:
    tuning = Tuning(gaze_weight=1.0, gaze_decay_constant=1.0)
    engine = ScoringEngine(tuning, width=100, height=100, own_pid=0)
    now = time.monotonic()
    engine.gaze_duration = {
        1: (1.0, now - 1.0),
        2: (1.0, now - 3.0),
    }
    weights = engine.score_samples([], 0.0, 0.0, 0.0, deque(), None)
    assert weights[1] == pytest.approx(math.exp(-1.0), rel=1e-3)
    assert weights[2] == pytest.approx(math.exp(-3.0), rel=1e-3)
    assert weights[1] > weights[2]
