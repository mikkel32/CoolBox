from collections import deque
import pytest

try:
    import numpy  # noqa: F401
except Exception:  # pragma: no cover - skip if NumPy unavailable
    pytest.skip("NumPy not available", allow_module_level=True)

from coolbox.utils.analysis.scoring_engine import ScoringEngine, tuning
from coolbox.utils.window_utils import WindowInfo
from coolbox.ui.views._fast_confidence import weighted_confidence as fast_wc


def test_fast_confidence_matches_engine() -> None:
    engine = ScoringEngine(tuning, 200, 200, own_pid=0)
    samples = [
        WindowInfo(1, (0, 0, 100, 100)),
        WindowInfo(2, (50, 0, 100, 100)),
    ]
    cursor_x = 75
    cursor_y = 50
    velocity = 0.0
    path_history = deque(maxlen=1)
    initial_active_pid = None

    expected = engine.weighted_confidence(
        samples, cursor_x, cursor_y, velocity, path_history, initial_active_pid
    )
    result = fast_wc(
        engine, samples, cursor_x, cursor_y, velocity, path_history, initial_active_pid
    )

    assert result == expected
